"""diag_n14_min.py — route ONLY n14 and trace why the y0 BFS comes back empty:
is the source actually reachable, is the goal sane, does the BFS find a path?"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from placer import place

ORTH, DIAG = coupling.ORTH, coupling.DIAG


def install_measured():
    def _foreign_plane(self, xz, net, owner):
        x, z = xz
        for dx, dz in ORTH:
            o = owner.get((x + dx, z + dz))
            if o is not None and o != net:
                return True
        for dx, dz in DIAG:
            o = owner.get((x + dx, z + dz))
            if o is None or o == net:
                continue
            if (x + dx, z) in owner or (x, z + dz) in owner:
                return True
        return False
    SH = [(dx, 0, dz) for dx, dz in ORTH] + [(0, 1, 0), (0, -1, 0)] + \
         [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    RB.BuildableRouter._foreign_plane = _foreign_plane
    RB.BuildableRouter._SHELL3D = SH


def main():
    install_measured()
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)

    # restrict to n14 only
    orig_once = r._route_once
    def only(nets, soft=False, verbose=False):
        return orig_once([n for n in nets if n == "n14"], soft=soft,
                         verbose=verbose)
    r._route_once = only
    res = r.route(verbose=False, max_rounds=3)
    print(f"n14 alone: failed={res.failed} wires={len(res.wires.get('n14', ()))}")
    print(f"  repeaters: {len(res.repeaters.get('n14', []))}")

    # direct BFS test
    s = pl.net_sources["n14"]
    src = (s[0], s[2])
    for k in pl.net_sinks["n14"]:
        goal = (k[0]-1, k[2])
        path = r._plane_bfs({src}, goal, "n14", soft=False)
        print(f"  BFS {src} -> {goal}: "
              f"{'None' if path is None else f'{len(path)} cells'}")

    # what blocks the straight line?
    print(f"\nstraight-line cells from {src} to sinks:")
    for k in pl.net_sinks["n14"]:
        goal = (k[0]-1, k[2])
        x, z = src
        while (x, z) != goal:
            if x != goal[0]:
                x += 1 if goal[0] > x else -1
            elif z != goal[1]:
                z += 1 if goal[1] > z else -1
            c = (x, z)
            in_cell = c in r.cell_xz
            in_pin = c in r.pin_net
            print(f"  {c}: cell={in_cell} pin={in_pin}")


if __name__ == "__main__":
    main()
