"""
win_diag_feed.py — for every sink whose feed is NOT electrically reachable,
print the feed cell's 4 neighbours and who owns them. A feed's west neighbour
is its ONLY entry lane (east = the pin, north/south = cell keep-out); if it is
owned, the sink is structurally starved and no layer count helps.
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import route_buildable as RB
from placer import place

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 10.0
    PF.DROP_COST = 8.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0)
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts} nets={len(placements)}", flush=True)

    # owner map of all placements (y0 layer focus)
    owner = {}
    for n, ps in placements.items():
        for role, x, y, z, *rest in ps:
            if role != "support":
                owner[(x, y, z)] = n

    y0 = pf.y0
    for net in pf.nets:
        if net not in placements:
            print(f"{net}: NO placements", flush=True)
            continue
        if pf._sink_fed(net, placements):
            continue
        print(f"\n{net}: some sink NOT fed", flush=True)
        cells = {(p[1], p[2], p[3]) for p in placements[net]
                 if p[0] == "dust"}
        src = pl.net_sources[net]
        comp = {src}
        dq = deque([src])
        while dq:
            cur = dq.popleft()
            for dx, dy, dz in [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1),
                               (0, 1, 0), (0, -1, 0)]:
                nx = (cur[0] + dx, cur[1] + dy, cur[2] + dz)
                if nx in cells and nx not in comp:
                    comp.add(nx)
                    dq.append(nx)
        for k in pl.net_sinks[net]:
            feed = (k[0] - 1, y0, k[2])
            if feed in comp:
                continue
            print(f"  sink pin={k} feed={feed} NOT fed", flush=True)
            for dx, dz in _H:
                nx = (feed[0] + dx, y0, feed[2] + dz)
                tag = "PIN " if nx == (k[0], y0, k[2]) else ""
                if nx in pf.cell_xz and nx != feed:
                    tag += "CELL "
                if nx in pf.pin_xz:
                    tag += "PINXZ "
                o = owner.get((nx[0], y0, nx[2]))
                print(f"    ({nx[0]},{nx[2]}) [{tag.strip() or 'free'}] "
                      f"owner={o}", flush=True)
            # is the feed's west lane occupied on ANY layer?
            wx, wz = feed[0] - 1, feed[2]
            for y in pf.layers:
                o = owner.get((wx, y, wz))
                print(f"    west lane ({wx},{y},{wz}) owner={o}", flush=True)


if __name__ == "__main__":
    main()
