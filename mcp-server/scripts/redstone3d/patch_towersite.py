"""
patch_towersite.py — the fix the enumeration pointed to, applied as a MEASURED
experiment before touching the router permanently.

Enumeration proved (enum_v2): n6/n5/n17 each have 20-24 fully feasible
(climb-site, cross-layer, delivery) triples, yet the router fails them, because
_extend_toward/_find_foothold choose the climb site by DISTANCE TO THE SINK and
never check whether the cross layer can actually get from there to the feed
column. For n6 it climbed at (35,0) — unreachable — while (1,38) works in 53
cross cells.

This patch replaces the climb-site choice with: among the net's own y0 cells,
pick one from which the cross layer PROVABLY reaches the feed column (same
_y2_free rule the router uses), preferring the shortest such approach. Everything
else in the router is untouched, so the effect is isolated and measurable.
"""
import sys, os, json, time
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter

_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def install(r):
    """Wrap _bridge_inner so the climb site is chosen by cross-reachability."""
    orig_extend = r._extend_toward

    def cross_reach(src_xz, goal_xz, net, cy, limit=8000):
        if not r._y2_free(src_xz, net, cy):
            return None
        seen = {src_xz}; prev = {}; q = deque([src_xz]); steps = 0
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
                if nx in seen or not r._y2_free(nx, net, cy):
                    continue
                if nx in r.rep_cells:
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    def patched_extend(net, placements, goal_xz):
        """Choose the extension END so that the tower placed just beyond it has a
        cross-layer path to the feed column. Falls back to the original when no
        cell qualifies (keeps every net the old logic could route)."""
        y0 = r.base_y
        cy = r.net_cross_y.get(net, y0 + 4)
        feed = goal_xz                      # goal_xz IS the pin's feed cell
        tree = [(p[1], p[3]) for p in placements.get(net, [])
                if p[0] == "dust" and p[2] == y0]
        s = r.pl.net_sources[net]
        tree.append((s[0], s[2]))
        # rank tree cells by cross-approach length (shortest first)
        best = None
        for t in tree:
            pth = cross_reach(t, feed, net, cy)
            if pth is None:
                continue
            if best is None or len(pth) < best[1]:
                best = (t, len(pth))
        if best is None:
            return orig_extend(net, placements, goal_xz)
        # emulate the original return shape: (anchor, adir, path). adir=None makes
        # _bridge_inner fall back to _find_foothold for the actual foot, but with
        # the anchor now guaranteed cross-reachable.
        return (best[0], None, None)

    r._extend_toward = patched_extend
    return r


def run(nls, mod, rounds, patched):
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    if patched:
        install(r)
    t0 = time.time()
    res = r.route(verbose=False, max_rounds=rounds)
    sh, _ = r._count_shorts(res)
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = 0
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                unfed += 1
    return sh, len(res.failed), unfed, res.total_wires(), time.time()-t0


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = sys.argv[1].split(",") if len(sys.argv) > 1 else ["alu1"]
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    print(f"{'module':12s} {'variant':9s} {'shorts':>6s} {'failed':>6s} "
          f"{'unfed':>5s} {'wires':>6s} {'secs':>5s}")
    for mod in mods:
        for patched in (False, True):
            sh, fn, uf, w, secs = run(nls, mod, rounds, patched)
            print(f"{mod:12s} {'patched' if patched else 'baseline':9s} "
                  f"{sh:6d} {fn:6d} {uf:5d} {w:6d} {secs:5.0f}")


if __name__ == "__main__":
    main()
