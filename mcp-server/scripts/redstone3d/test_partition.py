"""
Verify spatial-partition routing on one zone before injecting into route_gpu.
Uses existing GpuRouter + wavefront_batched + backtrace primitives.
Zone 0 of alu1 has 13 nets; color them locally (max 3 layers), route each layer
confined to zone 0's x-range [0,80].
"""
import sys, os, json, torch, time
from collections import defaultdict, Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_gpu import GpuRouter
nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
pl = place(nls["alu1"], col_gap=16, row_gap=10)
r = GpuRouter(pl, nlayers=8, layer_y=tuple(range(0, 16, 2)))
INF = float("inf")

# --- Partition ---
nets = [n for n in pl.net_sinks if pl.net_sources.get(n) and pl.net_sinks.get(n)]
W = 80
X0 = pl.bounds[0][0]

def zone_of(n):
    xs = [pl.net_sources[n][0]] + [k[0] for k in pl.net_sinks[n]]
    return set((x - X0) // W for x in xs)

local = [n for n in nets if len(zone_of(n)) == 1]
global_nets = [n for n in nets if len(zone_of(n)) > 1]
z0_nets = sorted([n for n in local if list(zone_of(n))[0] == 0])
print(f"zone 0: {len(z0_nets)} nets: {z0_nets}")

# --- Conflict graph ---
routes0, nbad0, net_idx = r.route(max_iters=12, verbose=False,
                                  short_pen=12.0, hist_inc=3.0, jitter=1.0, seed=0)
adj = r._conflict_graph(routes0, net_idx)

# --- Color zone 0 ---
adj_z0 = {n: adj[n] & set(z0_nets) for n in z0_nets}
order = sorted(z0_nets, key=lambda n: -len(adj_z0[n]))
CAP = 3
col = {}
layer_members = {}
for n in order:
    c = 1
    while True:
        members = layer_members.get(c, [])
        if len(members) < CAP and all(m not in adj_z0[n] for m in members):
            break
        c += 1
    col[n] = c
    layer_members.setdefault(c, []).append(n)
maxc = max(col.values())
print(f"zone 0 colors: max={maxc}, layers={maxc}")

# --- Route each layer ---
routes_out = {}
sweeps = r.X + r.Z + 4 * r.L
placed = None
for lc in range(1, maxc + 1):
    group = sorted([n for n in z0_nets if col[n] == lc])
    print(f"\n=== layer {lc}: {group} ===")
    # Cost: trunk layer = lc, x=[0,80], via at pins
    cost = torch.full((r.L, r.X, r.Z), INF, device=r.dev)
    cost[lc] = 1.0
    gx_lo = X0 - r.x0
    gx_hi = min((X0 + W) - r.x0, r.X)
    cost[lc, :max(0, gx_lo), :] = INF
    cost[lc, gx_hi:, :] = INF
    pin_set = set()
    for n in group:
        pin_set.add(r._g(pl.net_sources[n][0], pl.net_sources[n][2]))
        for k in pl.net_sinks[n]:
            pin_set.add(r._g(k[0], k[2]))
    for (gx, gz) in pin_set:
        cost[0:lc + 1, gx, gz] = 1.0
    if placed is not None:
        foreign = (placed > 0)
        keep = foreign.clone()
        for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            s = torch.roll(foreign, shifts=(dx, dz), dims=(1, 2))
            if dx == 1: s[:, 0, :] = False
            elif dx == -1: s[:, -1, :] = False
            if dz == 1: s[:, :, 0] = False
            elif dz == -1: s[:, :, -1] = False
            keep |= s
        cost[lc][keep[lc]] = INF

    # Negotiated
    gi = {n: i for i, n in enumerate(group)}
    hist = torch.zeros((r.L, r.X, r.Z), device=r.dev)
    best_gr = None; bestbad = 1 << 30
    for it in range(20):
        gr = {i: [] for i in range(len(group))}
        seeds = {}
        for n in group:
            seeds[gi[n]] = [(0,) + r._g(pl.net_sources[n][0], pl.net_sources[n][2])]
        sinks_of = {}
        for n in group:
            sinks_of[gi[n]] = [(0,) + r._g(k[0], k[2]) for k in pl.net_sinks[n]]
        cc = cost + hist
        msink = max(len(v) for v in sinks_of.values())
        for rd in range(msink):
            seed_list = [seeds[i] for i in range(len(group))]
            dist = r.wavefront_batched(seed_list, cc, sweeps)
            dcpu = dist.to("cpu")
            for i in range(len(group)):
                if rd >= len(sinks_of[i]):
                    continue
                gl, gx, gz = sinks_of[i][rd]
                if dcpu[i, 0, gx, gz].item() == INF:
                    continue
                path = r._backtrace_cpu(dcpu[i], 0, gx, gz)
                for cell in path:
                    is_pin = (cell[0] == 0 and (cell[1], cell[2]) in r.pin_cells)
                    if not is_pin:
                        if cell not in gr[i]:
                            gr[i].append(cell)
                        if cell not in seeds[i]:
                            seeds[i].append(cell)
        gocc = torch.zeros((r.L, r.X, r.Z), dtype=torch.int32, device=r.dev)
        for i, cells in gr.items():
            for (l, x, z) in cells:
                gocc[l, x, z] = i + 1
        nb = int(r._short_cells(gocc).sum().item())
        if nb < bestbad:
            bestbad = nb; best_gr = {i: list(v) for i, v in gr.items()}
        if nb == 0:
            break
        hist += r._short_cells(gocc).float() * 4.0
    print(f"  shorts={bestbad}")
    for i, cells in best_gr.items():
        routes_out[net_idx[group[i]]] = cells
    if placed is None:
        placed = torch.zeros((r.L, r.X, r.Z), dtype=torch.int32, device=r.dev)
    for i, cells in best_gr.items():
        for (l, x, z) in cells:
            placed[l, x, z] = net_idx[group[i]] + 1

# --- Connectivity audit ---
idx2 = {i: n for n, i in net_idx.items()}
unrouted = []
for i, cells in routes_out.items():
    n = idx2[i]
    S = set((c[0], c[1], c[2]) for c in cells)
    layers = set(c[0] for c in cells)
    # tl=1 trunk is directly above pins — no intermediate via needed
    has_via = (len(layers) >= 2)
    sg = r._g(pl.net_sources[n][0], pl.net_sources[n][2])
    near = lambda g: any((1, g[0]+dx, g[1]+dz) in S
                         for dx, dz in [(0,0),(1,0),(-1,0),(0,1),(0,-1)])
    ok = ((len(layers) >= 2 or near(sg)) and near(sg) and
          all(near(r._g(k[0], k[2])) for k in pl.net_sinks[n]))
    if not ok:
        unrouted.append((n, len(layers), near(sg),
                         [near(r._g(k[0], k[2])) for k in pl.net_sinks[n]]))
print(f"\nzone 0: routed {len(routes_out)} nets, unrouted={len(unrouted)}")
for u in unrouted[:4]: print(f"  {u}")

# Full short check
occ_final = r._occ_tensor(routes_out)
nbad_final = int(r._short_cells(occ_final).sum().item())
nw = sum(len(v) for v in routes_out.values())
print(f"zone 0 final: shorts={nbad_final} wires={nw}")
print(f"USABLE={'YES' if nbad_final==0 and not unrouted else 'NO'}")
