"""
win_suspend.py — check every repeater / wall torch / standing torch for a
support block beneath it (or behind it, for wall torches). Non-block items
(repeaters, torches, wires, targets) cannot float: no support = the block
never gets placed or never conducts in the build.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import route_buildable as RB
from placer import place

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 12.0
    PF.DROP_COST = 10.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0,
                         fanout_mult=12.0)
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})

    # full solid map: floor (y0-1) + supports + power_blocks + cell bodies
    solid = set()
    mn, mx = pl.bounds
    for x in range(mn[0] - 20, mx[0] + 20):
        for z in range(mn[2] - 20, mx[2] + 20):
            solid.add((x, mn[1] - 1, z))          # floor slab
    for s in res.supports:
        solid.add(s)
    for b in res.power_blocks:
        solid.add(b)
    for p in pl.occupancy:
        solid.add(p)                               # cell bodies (y0/y1)

    def chk(pos, kind, net):
        x, y, z = pos
        below = (x, y - 1, z)
        if y <= pf.y0:
            return True                            # on the floor
        if below in solid:
            return True
        print(f"  SUSPENDED {kind} {net} @{pos} "
              f"below={below} not solid", flush=True)
        return False

    n_rep = n_wt = n_t = 0
    for net, reps in res.repeaters.items():
        for (pos, f) in reps:
            n_rep += 1
            chk(pos, "repeater", net)
    for (pos, blk) in res.wall_torches:
        n_wt += 1
        x, y, z = pos
        # wall torch needs a solid block on the wall it faces (facing=the
        # direction it points; its support is BEHIND it)
        if "facing=east" in blk:
            wall = (x - 1, y, z)
        elif "facing=west" in blk:
            wall = (x + 1, y, z)
        elif "facing=north" in blk:
            wall = (x, y, z + 1)
        else:
            wall = (x, y, z - 1)
        if wall not in solid:
            print(f"  SUSPENDED wall_torch {net} @{pos} "
                  f"wall={wall} not solid", flush=True)
    for p in res.torches:
        n_t += 1
        chk(p, "torch", "?")
    print(f"\ntotals: repeaters={n_rep} wall_torches={n_wt} "
          f"torches={n_t}", flush=True)


if __name__ == "__main__":
    main()
