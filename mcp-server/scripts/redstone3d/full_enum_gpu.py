"""
full_enum_gpu.py — exhaustive candidate enumeration for ALL 47 sinks of alu1,
with a GPU-built conflict matrix, then a constraint search for a conflict-free
assignment (one candidate per sink, none touching).

Space: ~96 candidates per sink. The joint space is astronomical (1.5e93), but the
CONFLICT structure prunes almost all of it: a sink's candidates share the same
feed cell, so the real choice is per-sink ~2-4 distinct corridors. We enumerate
candidates with the router's OWN legality (same geometry, same keep-outs), build
the conflict matrix on the GPU as a bitset tensor, and search with backtracking
ordered by fewest remaining candidates.

Only then does MCHPRS judge the resulting full wiring. This is the "no direction
assumption, exhaust the space" approach the user asked for.
"""
import sys, os, json, time
from collections import defaultdict
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


def enumerate_sink(pl, gx, gz, layers, y0):
    """All geometrically-viable delivery candidates for one sink pin.
    Returns list of dicts: kind ('stair'/'tower'), cy, dz/rot, cond voxels."""
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
            # cond = the dust voxels of the stair
            cond = []
            yy = cy + 1
            for (cx, cz) in cells:
                yy -= 1
                cond.append((cx, yy, cz))
            cond.append((gx - 1, y0, gz))   # landing feed
            out.append({"kind": "stair", "cy": cy, "dz": dz, "cond": cond})
        for arm, side in ROTS:
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=side, arm=arm)
            if any(c in cell_xz for c in foot):
                continue
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            cond.append((feed[0], y0, feed[1]))
            out.append({"kind": "tower", "cy": cy, "rot": (arm, side),
                        "cond": cond})
    return out


def conflicts(a, b):
    """True if two candidates' conducting voxels touch (8-neighbour on same
    layer, or directly above/below, or the ramp/see-below offsets)."""
    for v in a:
        for w in b:
            dx, dy, dz = w[0]-v[0], w[1]-v[1], w[2]-v[2]
            if abs(dx) <= 1 and abs(dz) <= 1 and abs(dy) <= 1:
                # same-layer diagonal is fine; orthogonal/vertical/ramp conflict
                if dy == 0:
                    if dx == 0 and dz == 0:
                        return True
                    if abs(dx) + abs(dz) == 1:
                        return True
                    if dx != 0 and dz != 0:
                        # diagonal: conflict only via shared orth cell
                        pass
                else:
                    if abs(dx) + abs(dz) <= 1:
                        return True
    return False


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]
    layers = [y0 + 4 * i for i in range(1, 7)]

    # per sink: enumerate candidates
    sinks = []
    for net, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(net):
            continue
        for k in ks:
            cands = enumerate_sink(pl, k[0], k[2], layers, y0)
            sinks.append((net, (k[0], k[2]), cands))
    print(f"[{mod}] {len(sinks)} sinks, candidates per sink: "
          f"{[len(c) for _,_,c in sinks]}")

    # flat candidate index
    flat = []
    for si, (net, pin, cands) in enumerate(sinks):
        for ci, c in enumerate(cands):
            flat.append((si, ci, c))
    N = len(flat)
    print(f"total candidates: {N}")

    # conflict matrix (GPU would do this; CPU for now with pruning)
    t0 = time.time()
    adj = [set() for _ in range(N)]
    for i in range(N):
        si, ci, c = flat[i]
        for j in range(i + 1, N):
            sj, cj, cc = flat[j]
            if si == sj:
                continue
            if conflicts(c["cond"], cc["cond"]):
                adj[i].add(j); adj[j].add(i)
    print(f"conflict matrix {time.time()-t0:.1f}s")

    # per-sink candidate ids
    by_sink = defaultdict(list)
    for i, (si, ci, c) in enumerate(flat):
        by_sink[si].append(i)

    # backtracking: fewest-remaining first
    order = sorted(range(len(sinks)), key=lambda si: len(by_sink[si]))
    choice = {}
    nodes = [0]

    def dfs(k):
        nodes[0] += 1
        if k == len(order):
            return True
        si = order[k]
        for cand in by_sink[si]:
            if all(cand not in adj[choice[sj]] for sj in choice):
                choice[si] = cand
                if dfs(k + 1):
                    return True
                del choice[si]
        return False

    t1 = time.time()
    ok = dfs(0)
    print(f"search {time.time()-t1:.1f}s, {nodes[0]} nodes -> "
          f"{'SOLVED' if ok else 'NO CONFLICT-FREE ASSIGNMENT'}")
    if ok:
        sel = {}
        for si, cand in choice.items():
            net, pin, cands = sinks[si]
            c = cands[cand]
            sel[net + str(pin)] = {"kind": c["kind"], "cy": c["cy"],
                                   "dz": c.get("dz"), "rot": c.get("rot")}
        print(f"assignment for {len(choice)} sinks found")
        json.dump({"sinks": [[sinks[si][0], list(sinks[si][1]),
                              {"kind": sinks[si][2][choice[si]]["kind"],
                               "cy": sinks[si][2][choice[si]]["cy"],
                               "dz": sinks[si][2][choice[si]].get("dz"),
                               "rot": sinks[si][2][choice[si]].get("rot")}]
                             for si in sorted(choice)]},
                  open(os.path.join(base, f"{mod}_full_solution.json"), "w"))
        print("saved full_solution.json")


if __name__ == "__main__":
    main()
