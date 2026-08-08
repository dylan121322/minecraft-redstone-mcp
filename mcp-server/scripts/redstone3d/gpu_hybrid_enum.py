"""
gpu_hybrid_enum.py — GPU hybrid enumeration of the FULL wiring for the
bridge-needing sinks: source->bridge path AND the delivery, both enumerated,
conflicts judged on the GPU as a batch.

Why this is the missing piece:
  * delivery-only enumeration failed because the voxels were never connected to
    the source (apply_solution: 10/40, everything floated).
  * path enumeration on the CPU is the combinatorial explosion.
  * GPU wavefront (route_gpu.wavefront_batched) computes the shortest path in
    real geometry in parallel for all nets at once.

Plan:
  1. for each bridge sink, enumerate delivery candidates (stair/tower x cy x
     offset/rot) — CPU, small (96/sink, 6.7s for all).
  2. for each (net, sink, delivery), run the GPU wavefront from the net's source
     on the plane toward the bridge start; keep the TOP-K shortest paths as the
     approach candidates. Each candidate = full path + delivery voxels.
  3. build the GPU conflict matrix over all candidates (a boolean tensor of
     occupied voxels per candidate; conflicts = any shared 26-shell cell).
  4. backtracking search (CPU) for one candidate per sink with zero conflicts.
  5. MCHPRS judges the full chip.
"""
import sys, os, json, time
from collections import defaultdict
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import torch
from placer import place
from route_gpu import GpuRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
DZS = (0, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8)
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def delivery_voxels(pl, gx, gz, y0, cy, kind, extra):
    feed = (gx - 1, gz)
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
    if kind == "stair":
        dz = extra
        depth = cy + 1 - y0
        zz = gz + dz
        cells = [(gx - depth + i, zz) for i in range(1, depth + 1)]
        if any(c in cell_xz for c in cells):
            return None
        cond = []
        yy = cy + 1
        for (cx, cz) in cells:
            yy -= 1
            cond.append((cx, yy, cz))
        cond.append((gx - 1, y0, gz))
        return cond
    else:
        arm, side = extra
        cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                           side=side, arm=arm)
        if any(c in cell_xz for c in foot):
            return None
        cond = [(x, y, z) for (x, y, z, b) in cells if b == DUST or "torch" in b]
        cond.append((feed[0], y0, feed[1]))
        return cond


def conflicts(a, b):
    sa = set(a)
    for v in b:
        for dx, dy, dz in SHELL:
            if (v[0]+dx, v[1]+dy, v[2]+dz) in sa:
                return True
    return False


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else min(32, os.cpu_count() or 8)
    pl = place(nls[mod], col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]
    layers = [y0 + 4 * i for i in range(1, 7)]

    # 1. the bridge-needing sinks (y0-fail) — same detection as the router
    from route_buildable import BuildableRouter
    r0 = BuildableRouter(pl, margin=16)
    res0 = r0.route(verbose=False, max_rounds=3)
    own = {}
    for n in res0.wires:
        own[n] = {(p[0], p[2]) for p in res0.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res0.repeaters.get(n, [])}
    bridge_sinks = []
    for n, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(n):
            continue
        for k in ks:
            if (k[0]-1, k[2]) not in own.get(n, set()):
                bridge_sinks.append((n, (k[0], k[2])))
    print(f"[{mod}] bridge sinks: {len(bridge_sinks)} {bridge_sinks}")

    # 2. build the GPU router's world once; use wavefront per net for approach
    r = GpuRouter(pl, nlayers=30, layer_y=tuple(range(0, 60, 2)))
    # net -> source grid pos
    src_grid = {}
    for n, p in pl.net_sources.items():
        src_grid[n] = r._g(p[0], p[2])

    # enumerate FULL candidates: delivery + GPU approach path
    candidates = defaultdict(list)   # sink_idx -> [(voxels, meta)]
    INF = float("inf")
    cost = torch.full((r.L, r.X, r.Z), 1.0, device=r.dev)
    cost[r.block] = INF

    for si, (net, (gx, gz)) in enumerate(bridge_sinks):
        feed = (gx - 1, gz)
        src = src_grid[net]
        # GPU wavefront from the source (y0 layer) over the 3D cost field
        d3 = r.wavefront([(0, src[0], src[1])], cost, max_iters=400)
        for cy in layers:
            depth = cy + 1 - y0
            for dz in DZS:
                dv = delivery_voxels(pl, gx, gz, y0, cy, "stair", dz)
                if dv is None:
                    continue
                # approach: the stair top cell
                top = dv[-2] if len(dv) > 1 else None
                if top is None:
                    continue
                # wavefront distance to the stair top's grid cell (y0 plane)
                gtop = r._g(top[0], top[2])
                dist = d3[0, gtop[0], gtop[1]].item()
                if dist < INF:
                    # backtrace the ACTUAL path from the source to the stair top
                    path = r._backtrace_cpu(d3.cpu(), 0, gtop[0], gtop[1])
                    # path = list of (l,gx,gz); map to world voxels (y0 plane
                    # only: l==0 cells) plus the final delivery join
                    wpath = [(p[1] + r.x0, y0, p[2] + r.z0) for p in path
                             if p[0] == 0]
                    full = list(dv) + wpath
                    candidates[si].append((full, ("stair", cy, dz)))
            for arm, side in ROTS:
                dv = delivery_voxels(pl, gx, gz, y0, cy, "tower", (arm, side))
                if dv is None:
                    continue
                candidates[si].append((dv, ("tower", cy, (arm, side))))
        print(f"  {net}@{feed}: {len(candidates[si])} full candidates "
              f"(delivery+reachable)", flush=True)

    # 3. GPU conflict matrix over full candidates
    flat = []
    for si in range(len(bridge_sinks)):
        for ci, (vox, meta) in enumerate(candidates[si]):
            flat.append((si, ci, vox, meta))
    N = len(flat)
    print(f"total full candidates: {N}")
    t0 = time.time()
    # batch conflict: build occupancy sets; GPU via hashing is overkill — the
    # candidates are few (96/sink max); CPU pair check is fine now that they're
    # the FULL paths. Use CPU for the small matrix.
    adj = [set() for _ in range(N)]
    for i in range(N):
        si, ci, vox, meta = flat[i]
        for j in range(i + 1, N):
            sj, cj, vox2, meta2 = flat[j]
            if si != sj and conflicts(vox, vox2):
                adj[i].add(j); adj[j].add(i)
    print(f"conflict matrix {time.time()-t0:.1f}s ({N} candidates)")

    # 4. backtracking
    by_sink = defaultdict(list)
    for i, (si, ci, vox, meta) in enumerate(flat):
        by_sink[si].append(i)
    order = sorted(range(len(bridge_sinks)), key=lambda s: len(by_sink[s]))
    choice = {}
    nodes = [0]
    t1 = time.time()

    def dfs(k):
        nodes[0] += 1
        if k == len(order):
            return True
        si = order[k]
        for cand in by_sink[si]:
            if all(cand not in adj[choice[s]] for s in choice):
                choice[si] = cand
                if dfs(k + 1):
                    return True
                del choice[si]
        return False

    ok = dfs(0)
    print(f"search {time.time()-t1:.1f}s, {nodes[0]} nodes -> "
          f"{'SOLVED' if ok else 'NO ASSIGNMENT'}")
    if ok:
        out = []
        for si in sorted(choice):
            f = flat[choice[si]]
            net, (gx, gz) = bridge_sinks[si]
            out.append({"net": net, "pin": [gx, gz],
                        "kind": f[3][0], "cy": f[3][1], "extra": f[3][2],
                        "voxels": f[2]})
        json.dump({"sinks": out},
                  open(os.path.join(base, f"{mod}_gpu_hybrid.json"), "w"))
        print(f"saved gpu_hybrid.json ({len(out)} sinks, full paths)")


if __name__ == "__main__":
    main()
