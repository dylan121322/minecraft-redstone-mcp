"""
enum_v2.py — corrected enumeration model.

v1 flaw (found by tracing n6): it enumerated only the DELIVERY (the down tower in
the pin's feed column) and declared 18 candidates "feasible", but the router still
failed — because the signal also has to REACH the tower top. The trace showed

    pick_down_tower(cy=16) -> rot found        (delivery is fine)
    y2_bfs(cy=16, src=1)   -> None             (approach is impossible)

the climb tower stood at (35,0) while the sink was at (41,38): the cross run had
to cross 38 cells of z through a plane guarded by an 8-neighbourhood check, and
never made it.

So a candidate must be a PAIR: (climb site, delivery) plus a proven cross path
between them. This version enumerates
    climb site   : cells of the net's own y0 tree that can host a tower
    cross layer  : y0+4k
    delivery     : down-tower rotation in the feed column
and tests reachability on the cross layer with the SAME _y2_free rule the router
uses, so a "feasible" candidate here is feasible for the router too.
"""
import sys, os, json, time
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def cross_reachable(r, src_xz, goal_xz, net, cy, limit=20000):
    """BFS on the cross layer with the router's own legality test. Returns the
    path or None. Mirrors _y2_bfs but without the x-penalty weighting so we test
    pure REACHABILITY (the router's weighting only changes which path it takes)."""
    if not r._y2_free(src_xz, net, cy):
        return None
    seen = {src_xz}
    prev = {}
    q = deque([src_xz])
    steps = 0
    while q and steps < limit:
        cur = q.popleft(); steps += 1
        if cur == goal_xz:
            path = [cur]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        for dx, dz in _H:
            nx = (cur[0]+dx, cur[1]+dz)
            if nx in seen:
                continue
            if not r._y2_free(nx, net, cy):
                continue
            if nx in r.rep_cells:
                continue
            seen.add(nx); prev[nx] = cur; q.append(nx)
    return None


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    focus = sys.argv[3] if len(sys.argv) > 3 else None

    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    sh, _ = r._count_shorts(res)
    y0 = pl.bounds[0][1]
    print(f"[{mod}] shorts={sh} failed={len(res.failed)}: {res.failed}")

    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    print(f"unfed sinks: {len(unfed)}")

    layers = [y0 + 4 * i for i in range(1, 7)]
    for net, (gx, gz) in unfed:
        if focus and net != focus:
            continue
        feed = (gx - 1, gz)
        tree = sorted(own.get(net, ()))
        print(f"\n{net}@({gx},{gz}) feed={feed} y0-tree cells={len(tree)}")
        n_delivery = 0
        n_full = 0
        examples = []
        for cy in layers:
            # deliveries that fit
            deliveries = []
            for arm, side in ROTS:
                cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                                   side=side, arm=arm)
                if any(c in r.cell_xz or c in r.pin_net for c in foot):
                    continue
                cond = [(x, y, z) for (x, y, z, b) in cells
                        if b == DUST or "torch" in b]
                bad = False
                for v in cond:
                    o = r.owner3d.get(v)
                    if o is not None and o != net:
                        bad = True; break
                if bad:
                    continue
                deliveries.append((arm, side))
            n_delivery += len(deliveries)
            if not deliveries:
                continue
            # can the cross layer reach the feed column from ANY tree cell?
            reach_from = None
            for t in tree[:40]:            # bound the probe
                pth = cross_reachable(r, t, feed, net, cy)
                if pth:
                    reach_from = (t, len(pth)); break
            if reach_from:
                n_full += len(deliveries)
                examples.append((cy, deliveries[0], reach_from))
        print(f"   deliveries that fit (ignoring approach): {n_delivery}")
        print(f"   deliveries WITH a proven cross approach:  {n_full}")
        for cy, rot, (t, plen) in examples[:4]:
            print(f"      cy={cy} rot={rot} approach from {t} ({plen} cross cells)")
        if n_delivery and not n_full:
            print("   => v1 called this feasible; the APPROACH is what fails "
                  "(this is the real blocker class)")


if __name__ == "__main__":
    main()
