"""
full_enum_par.py — PARALLEL exhaustive enumeration of delivery candidates for all
47 alu1 sinks, with a parallel conflict matrix and a backtracking search for a
conflict-free assignment. Uses every core: candidate enumeration, conflict rows
and the search's ordering all run on a ProcessPool (32 workers on the Win box).

Space: ~96 candidates per sink geometrically; the joint space is astronomical
(1.5e93), but the conflict matrix prunes: candidates of one sink are mutually
exclusive, and most cross-sink candidates touch some other sink's feed cell.
Search is ordered fewest-remaining-first so the branch factor collapses fast.

Only after a conflict-free assignment is found does MCHPRS judge the wiring.
"""
import sys, os, json, time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
DZS = (0, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8)
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def conflicts(a, b):
    """True if two candidate voxel sets touch (orthogonal/vertical/ramp)."""
    sa, sb = set(a), set(b)
    for v in sa:
        for dx, dy, dz in SHELL:
            if (v[0]+dx, v[1]+dy, v[2]+dz) in sb:
                return True
    return False


def enumerate_sink(args):
    pl, gx, gz, layers, y0, net = args
    feed = (gx - 1, gz)
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
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
            out.append((net, "stair", cy, dz, None, cond))
        for arm, side in ROTS:
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=side, arm=arm)
            if any(c in cell_xz for c in foot):
                continue
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            cond.append((feed[0], y0, feed[1]))
            out.append((net, "tower", cy, None, (arm, side), cond))
    return out


def build_rows(args):
    """Conflict rows for candidate ids [a0, a1) against all ids."""
    flat, a0, a1 = args
    rows = []
    for i in range(a0, a1):
        si, ci, c = flat[i]
        row = []
        for j in range(len(flat)):
            if i == j:
                continue
            sj, cj, cc = flat[j]
            if si == sj:
                continue
            if conflicts(c[5], cc[5]):
                row.append(j)
        rows.append((i, row))
    return rows


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else min(32, os.cpu_count() or 8)
    pl = place(nls[mod], col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]
    layers = [y0 + 4 * i for i in range(1, 7)]

    # parallel candidate enumeration
    jobs = []
    for net, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(net):
            continue
        for k in ks:
            jobs.append((pl, k[0], k[2], layers, y0, net))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(enumerate_sink, j) for j in jobs]
        per_sink = [f.result() for f in futs]
    sinks = []
    flat = []
    for si, cands in enumerate(per_sink):
        sinks.append(cands)
        for ci, c in enumerate(cands):
            flat.append((si, ci, c))
    N = len(flat)
    print(f"[{mod}] {len(sinks)} sinks, {N} candidates "
          f"(enumerated {time.time()-t0:.1f}s)", flush=True)

    # parallel conflict rows
    t1 = time.time()
    chunk = max(1, N // workers)
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = []
        for a0 in range(0, N, chunk):
            futs.append(ex.submit(build_rows, (flat, a0, min(a0 + chunk, N))))
        for f in futs:
            rows.extend(f.result())
    adj = {}
    for i, row in rows:
        adj[i] = set(row)
    print(f"conflict matrix {time.time()-t1:.1f}s ({N} nodes)", flush=True)

    # backtracking with fewest-remaining ordering
    by_sink = defaultdict(list)
    for i, (si, ci, c) in enumerate(flat):
        by_sink[si].append(i)
    order = sorted(range(len(sinks)), key=lambda si: len(by_sink[si]))
    choice = {}
    nodes = [0]

    def dfs(k):
        nodes[0] += 1
        if k == len(order):
            return True
        si = order[k]
        # fewest-conflicting-candidates first within this sink
        cands = sorted(by_sink[si],
                       key=lambda c: sum(1 for s in choice
                                         if c in adj[choice[s]]))
        for cand in cands:
            if all(cand not in adj[choice[s]] for s in choice):
                choice[si] = cand
                if dfs(k + 1):
                    return True
                del choice[si]
        return False

    t2 = time.time()
    ok = dfs(0)
    print(f"search {time.time()-t2:.1f}s, {nodes[0]} nodes -> "
          f"{'SOLVED' if ok else 'NO ASSIGNMENT'}", flush=True)
    if ok:
        out_sinks = []
        for si in sorted(choice):
            cand = sinks[si][choice[si]]
            out_sinks.append({"net": cand[0], "kind": cand[1], "cy": cand[2],
                              "dz": cand[3], "rot": cand[4]})
        json.dump({"sinks": out_sinks},
                  open(os.path.join(base, f"{mod}_full_solution.json"), "w"))
        print(f"saved full_solution.json ({len(out_sinks)} sinks)")


if __name__ == "__main__":
    main()
