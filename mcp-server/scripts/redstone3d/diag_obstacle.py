"""diag_obstacle.py — for a net whose y0 planar route failed, find WHERE and HOW
WIDE the blockage is. The bridge should hop only that obstacle (a few cells), not
fly the whole way to the sink on the cross plane: n8 currently lays 133 cross
cells and n13 216, which is the opposite of minimal. Measuring the real obstacle
width tells us how short a hop is actually needed."""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter, _H


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n8"
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    # replay the y0 phase only, in the same order route() uses
    nets = [n for n in pl.net_sinks
            if pl.net_sources.get(n) and pl.net_sinks.get(n)]
    def span(n):
        s = pl.net_sources[n]; ks = pl.net_sinks[n]
        return max(abs(s[0]-k[0])+abs(s[2]-k[2]) for k in ks)
    nets.sort(key=lambda n: (len(pl.net_sinks[n]), span(n)))
    r.owner0 = {}
    blocked_for = {}
    for n in nets:
        s = pl.net_sources[n]; src = (s[0], s[2])
        r.owner0.setdefault(src, n)
        tree = {src}; first = True
        for k in sorted(pl.net_sinks[n], key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2])):
            goal = (k[0], k[2])
            path = r._plane_bfs(tree, goal, n, soft=False)
            if path is None:
                blocked_for.setdefault(n, []).append(goal)
                continue
            for (x, z) in path:
                r.owner0[(x, z)] = n
                if (x, z) not in r.pin_net:
                    tree.add((x, z))
            if first:
                tree.discard(src); first = False
    print(f"nets whose y0 route failed: {len(blocked_for)}")
    for n, gs in blocked_for.items():
        print(f"  {n}: {len(gs)} sink(s) unreachable on y0 -> {gs}")
    if net not in blocked_for:
        print(f"{net} routed fine on y0 (no bridge needed at that point)")
        return
    # For the target net: flood from its tree and see how far it gets, then find
    # the nearest cell to the goal it COULD reach, and what blocks the gap.
    s = pl.net_sources[net]; src = (s[0], s[2])
    goal = blocked_for[net][0]
    seen = {src}; q = deque([src])
    while q:
        cur = q.popleft()
        for dx, dz in _H:
            nx = (cur[0]+dx, cur[1]+dz)
            if nx in seen or not r._in_box(nx):
                continue
            if nx in r.cell_xz or nx in r.pin_net:
                continue
            o = r.owner0.get(nx)
            if o is not None and o != net:
                continue
            if r._foreign_plane(nx, net, r.owner0) or \
               r._foreign_pin_adj(nx, net, goal):
                continue
            seen.add(nx); q.append(nx)
    best = min(seen, key=lambda c: abs(c[0]-goal[0]) + abs(c[1]-goal[1]))
    gap = abs(best[0]-goal[0]) + abs(best[1]-goal[1])
    print(f"{net}: reachable cells={len(seen)}, closest to goal {goal} is {best}, "
          f"remaining gap={gap}")
    # what sits in the straight line between best and goal?
    print("  cells along the gap:")
    cx, cz = best
    for _ in range(gap):
        if cx != goal[0]:
            cx += 1 if goal[0] > cx else -1
        elif cz != goal[1]:
            cz += 1 if goal[1] > cz else -1
        o = r.owner0.get((cx, cz)); pin = r.pin_net.get((cx, cz))
        cell = (cx, cz) in r.cell_xz
        print(f"    ({cx},{cz}): owner={o} pin={pin} cell_body={cell}")


if __name__ == "__main__":
    main()
