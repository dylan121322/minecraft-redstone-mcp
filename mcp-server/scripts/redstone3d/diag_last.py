"""
diag_last.py — the parallel sweep drove alu1 from 9 unfed sinks to exactly ONE
(yield=n13+n17+n7+n8, 0 shorts, 28/29 nets). Five-net yields do not improve on
that, so the last sink is not an ordering problem. This tells us WHAT it is:

  * which sink is it, and does it have ANY viable (climb-site, layer, rotation)
    triple at all (approach included)?
  * if yes -> the router's control flow still cannot reach it (fixable in code)
  * if no  -> report exactly what occupies every candidate, i.e. whether the
    placement or the baseline route has to change.
"""
import sys, os, json
from collections import deque, Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    ys = set((sys.argv[2] if len(sys.argv) > 2 else "n13+n17+n7+n8").split("+"))
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in ys]
        tail = [n for n in nets if n in ys]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)
    sh, _ = r._count_shorts(res)
    y0 = pl.bounds[0][1]

    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    print(f"[{mod}] yield={sorted(ys)} shorts={sh} failed={res.failed} "
          f"unfed={len(unfed)}")
    if not unfed:
        print("ALL SINKS FED — nothing to diagnose")
        return

    occ = {}
    for n, ws in res.wires.items():
        for p in ws:
            occ[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occ[q] = n
    for p in res.torches:
        occ[p] = res.torch_nets.get(p, "?")
    for (q, _b) in res.wall_torches:
        occ[q] = res.wall_torch_nets.get(q, "?")

    def reach(src, feed, net, cy, limit=8000):
        if not r._y2_free(src, net, cy):
            return None
        seen = {src}; prev = {}; q = deque([src]); st = 0
        while q and st < limit:
            cur = q.popleft(); st += 1
            if cur == feed:
                n = 0; c = cur
                while c in prev:
                    c = prev[c]; n += 1
                return n
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen or nx in r.rep_cells:
                    continue
                if not r._y2_free(nx, net, cy):
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    for net, (gx, gz) in unfed:
        feed = (gx - 1, gz)
        s = pl.net_sources[net]
        tree = sorted(own.get(net, ()) | {(s[0], s[2])})
        print(f"\n=== {net}@({gx},{gz}) feed={feed} y0-tree={len(tree)} ===")
        print(f"   source={s}  sinks={pl.net_sinks[net]}")
        n_deliv = n_full = 0
        blockers = Counter()
        for cy in [y0 + 4 * i for i in range(1, 8)]:
            rots_ok = []
            for arm, side in ROTS:
                cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                                   side=side, arm=arm)
                if any(c in r.cell_xz or c in r.pin_net for c in foot):
                    continue
                cond = [(x, y, z) for (x, y, z, b) in cells
                        if b == DUST or "torch" in b]
                who = set()
                for v in cond:
                    o = occ.get(v)
                    if o is not None and o != net:
                        who.add(o)
                    for dx, dy, dz in SHELL:
                        o = occ.get((v[0]+dx, v[1]+dy, v[2]+dz))
                        if o is not None and o != net:
                            who.add(o)
                if who:
                    for w in who:
                        blockers[w] += 1
                    continue
                rots_ok.append((arm, side))
            n_deliv += len(rots_ok)
            if not rots_ok:
                continue
            hit = None
            for t in tree[:80]:
                pl2 = reach(t, feed, net, cy)
                if pl2 is not None:
                    hit = (t, pl2); break
            if hit:
                n_full += len(rots_ok)
                print(f"   cy={cy}: {len(rots_ok)} rotations, approach from "
                      f"{hit[0]} in {hit[1]} cross cells  <-- VIABLE")
            else:
                print(f"   cy={cy}: {len(rots_ok)} rotations fit but NO cross "
                      f"approach from any of {len(tree)} tree cells")
        print(f"   totals: deliveries={n_deliv} fully-viable={n_full}")
        if blockers:
            print(f"   delivery blockers: {dict(blockers.most_common(6))}")
        if n_full:
            print("   => VIABLE solution exists; the router's control flow "
                  "does not find it (code fix, not a space problem)")
        elif n_deliv:
            print("   => delivery fits but approach never does: the cross plane "
                  "around this sink is sealed (needs a different climb site or "
                  "an extra cross layer)")
        else:
            print("   => no delivery fits at all: placement/baseline must change")


if __name__ == "__main__":
    main()
