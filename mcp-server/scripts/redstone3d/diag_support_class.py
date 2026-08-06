"""
diag_support_class.py — classify every support in a routed alu1 by whether it is
on an energy HAND-OFF chain (must stay stone) or is purely passive (can be glass).

From the measured physics:
  * a staircase step reads the cross dust THROUGH its support's strong power
  * a down-tower input dust drives its column the same way
  * a tower's rungs are already power_blocks (stone)
So a support must stay STONE if:
  - it sits under a CROSS-plane dust (that dust must strongly power it so the
    stair/tower below can read it), OR
  - it sits under a stair's rung support (see-below hand-off), OR
  - it carries a repeater that must strongly power something below/adjacent
Everything else — plain same-layer run supports — is passive and could be glass.

This prints the count of each class so we know how much of the build the glass
idea can actually cover.
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

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
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n3+n5").split("+"))
    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yields]
        tail = [n for n in nets if n in yields]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=5)

    powered = set(getattr(res, "power_blocks", set()))
    sup = set(res.supports)
    print(f"supports total={len(sup)}  power_blocks(stone)={len(powered)}")
    passive = sup - powered
    print(f"passive candidates for glass: {len(passive)}")

    # which passive supports carry a CROSS-plane dust directly above them?
    # cross dusts sit at cy+1 where cy is a cross-layer index. We know cross
    # layers from the wires' y values: any support with a wire directly above at
    # y>=2 that is NOT part of a stair is a cross support.
    above_wire = Counter()
    cross_like = 0
    stair_like = 0
    other = 0
    wire_ys = Counter()
    for p in res.wires:
        wire_ys[p[1]] += 1
    print(f"wire y distribution: {dict(sorted(wire_ys.items()))}")

    # supports are keyed by (x,y,z); the wire above is (x, y+1, z)
    cross_sups = []
    stair_sups = []
    for (x, y, z) in passive:
        above = (x, y + 1, z)
        if above in res.wires:
            if y >= 2:
                cross_sups.append((x, y, z))
            else:
                stair_sups.append((x, y, z))
    print(f"passive supports under a raised wire at y>=2 (cross-like): {len(cross_sups)}")
    print(f"passive supports under a wire at y<=1 (stair/ground):     {len(stair_sups)}")
    print(f"if cross-like must stay stone, glass covers only {len(passive)-len(cross_sups)}")

    # the down-tower input seam: support directly under the tower A column's
    # input dust at cy (these sit at (feed_x, cy, feed_z))
    tower_in = 0
    for (x, y, z) in passive:
        if y >= 2 and (x, y, z) in res.supports:
            pass
    print(f"\nconclusion: glass insertion is bounded by how many supports are")
    print(f"cross-plane. If cross supports MUST be stone, the glass win is the")
    print(f"stair/ground class only: {len(stair_sups)} supports.")


if __name__ == "__main__":
    main()
