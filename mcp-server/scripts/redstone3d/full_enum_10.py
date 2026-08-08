"""
full_enum_10.py — exhaustive enumeration of the ONLY 10 sinks that need a bridge
(y0-fail), with the rest of the 37 sinks routed on y0 as the router does.

Space: 10 sinks x ~96 delivery candidates = 960 candidates; the joint space is
96^10 ~ 6.6e19 but the conflict matrix plus fewest-remaining-first backtracking
collapses it (the router's own geometry makes most candidates of one sink share
the same feed cell and most cross-sink pairs touch).

Each candidate = (stair|tower, cy, dz/rot) + its conducting voxels. The solver
picks one candidate per sink with no pair touching. The chosen assignment is
saved; the router then applies it and MCHPRS judges the whole chip.
"""
import sys, os, json, time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
DZS = (0, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8)
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def conflicts(a, b):
    """True if any conducting voxel of a touches one of b (orthogonal,
    vertical, or ramp/see-below — the measured coupling rules)."""
    sa = set(a)
    for v in b:
        for dx, dy, dz in SHELL:
            if (v[0]+dx, v[1]+dy, v[2]+dz) in sa:
                return True
    return False


def rows_chunk(args):
    flat_, a0, a1 = args
    out = []
    for i in range(a0, a1):
        si, ci, c = flat_[i]
        row = set()
        for j in range(len(flat_)):
            sj, cj, cc = flat_[j]
            if si != sj and conflicts(c[4], cc[4]):
                row.add(j)
        out.append((i, row))
    return out


def enum_sink(pl, gx, gz, y0, layers):
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
    feed = (gx - 1, gz)
    out = []
    for cy in layers:
        depth = cy + 1 - y0
        for dz in DZS:
            zz = gz + dz
            cells = [(gx - depth + i, zz) for i in range(1, depth + 1)]
            if any(c in cell_xz for c in cells):
                continue
            cond = []
            yy = cy + 1
            for (cx, cz) in cells:
                yy -= 1
                cond.append((cx, yy, cz))
            cond.append((gx - 1, y0, gz))
            out.append(("stair", cy, dz, None, cond))
        for arm, side in ROTS:
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=side, arm=arm)
            if any(c in cell_xz for c in foot):
                continue
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            cond.append((feed[0], y0, feed[1]))
            out.append(("tower", cy, None, (arm, side), cond))
    return out


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else min(32, os.cpu_count() or 8)
    pl = place(nls[mod], col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]
    layers = [y0 + 4 * i for i in range(1, 7)]

    # the 10 bridge-needing sinks, from the router's y0 pass
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=3)
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    bridge_sinks = []
    for n, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(n):
            continue
        for k in ks:
            if (k[0]-1, k[2]) not in own.get(n, set()):
                bridge_sinks.append((n, (k[0], k[2])))
    print(f"[{mod}] bridge-needing sinks: {len(bridge_sinks)} {bridge_sinks}")

    # enumerate candidates per sink
    cands_list = []
    flat = []
    for si, (net, (gx, gz)) in enumerate(bridge_sinks):
        cs = enum_sink(pl, gx, gz, y0, layers)
        cands_list.append(cs)
        for ci, c in enumerate(cs):
            flat.append((si, ci, c))
    N = len(flat)
    per = [len(c) for c in cands_list]
    print(f"candidates per sink: {per}  total={N}")

    # parallel conflict rows
    t0 = time.time()
    chunk = max(1, N // workers)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(rows_chunk, (flat, a, min(a + chunk, N)))
                for a in range(0, N, chunk)]
        adj = {}
        for f in futs:
            for i, row in f.result():
                adj[i] = row
    print(f"conflict matrix {time.time()-t0:.1f}s ({N} candidates)", flush=True)

    # backtracking fewest-remaining-first
    by_sink = defaultdict(list)
    for i, (si, ci, c) in enumerate(flat):
        by_sink[si].append(i)
    order = sorted(range(len(bridge_sinks)), key=lambda si: len(by_sink[si]))
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
          f"{'SOLVED' if ok else 'NO ASSIGNMENT'}", flush=True)
    if ok:
        out = []
        for si in sorted(choice):
            net, (gx, gz) = bridge_sinks[si]
            flat_i = choice[si]
            # flat_i = (si, ci, c); recover ci
            ci = flat[flat_i][1]
            c = cands_list[si][ci]
            out.append({"net": net, "pin": [gx, gz], "kind": c[0], "cy": c[1],
                        "dz": c[2], "rot": c[3]})
        json.dump({"sinks": out},
                  open(os.path.join(base, f"{mod}_bridge10_solution.json"), "w"))
        print(f"saved bridge10_solution.json ({len(out)} sinks)")


if __name__ == "__main__":
    main()
