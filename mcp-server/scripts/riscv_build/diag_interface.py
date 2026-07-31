"""
diag_interface.py — why is the module-to-module interface unstable?

The three cascade cases fail differently (0, then a constant 14, then 0), which is
the signature of an interface whose two sides disagree rather than of one broken
gadget. So instead of guessing: for each joint, print what the upstream module
actually placed at its `out`, what the connector expects at its `a`, what the
connector places, what the downstream module has at its `in`, and who owns each of
those cells. A disagreement becomes visible instead of inferred.

Also checks the obvious overlap hazards: does one module's skin sit on another
module's interface cell, and does the connector's own skin seal an endpoint it is
supposed to leave open?
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
from trunk_box import TrunkBox
from delivery_box import DeliveryBox, TowerBox
from connector import Connector

S = "minecraft:stone"


def build(plane, run_to, row, sink_x, base_y=0):
    tb = TrunkBox(src_cell=(0, base_y, 10), plane=plane,
                  run_to_x=run_to, leg_to_z=row)
    drop = plane - base_y
    if drop <= 4:
        db = DeliveryBox(anchor=(sink_x - 2 - drop, plane, row), drop=drop)
    else:
        probe = TowerBox(anchor=(0, plane, row), drop=drop)
        span = probe.out_cell[0] - probe.in_cell[0]
        db = TowerBox(anchor=(sink_x - 2 - span, plane, row), drop=drop)
    cn = Connector(a_out=tb.out_cell, b_in=db.in_cell)
    return tb, cn, db


def show(label, cell, mods):
    """What does each module put at this cell?"""
    parts = []
    for name, m in mods:
        b = m.blocks.get(cell)
        if b is not None:
            parts.append(f"{name}={b.replace('minecraft:', '')[:20]}")
    if not parts:
        parts.append("nothing")
    print(f"    {label:26s} {cell}  {' | '.join(parts)}")


def main():
    for plane, run_to, row, sink_x in ((5, 60, 30, 120),
                                       (5, 150, 45, 260),
                                       (9, 100, 40, 200),
                                       (13, 200, 60, 320)):
        tb, cn, db = build(plane, run_to, row, sink_x)
        mods = [("trunk", tb), ("conn", cn), ("deliv", db)]
        print(f"case plane={plane} run_to={run_to} row={row} sink_x={sink_x} "
              f"conn_len={cn.length}")
        show("trunk.out", tb.out_cell, mods)
        show("conn.a", cn.a_cell, mods)
        show("conn.b", cn.b_cell, mods)
        show("deliv.in", db.in_cell, mods)
        show("deliv.out", db.out_cell, mods)

        # is the connector actually adjacent to what it claims?
        d_a = sum(abs(a - b) for a, b in zip(cn.a_cell, tb.out_cell))
        d_b = sum(abs(a - b) for a, b in zip(cn.b_cell, db.in_cell))
        print(f"    endpoint distance: trunk.out<->conn.a = {d_a}, "
              f"conn.b<->deliv.in = {d_b}")

        # does any module's skin land on another module's interface cell?
        for name, m in mods:
            for other, om in mods:
                if name == other:
                    continue
                for iface, icell in (("in", getattr(om, "in_cell", None)),
                                     ("out", getattr(om, "out_cell", None)),
                                     ("a", getattr(om, "a_cell", None)),
                                     ("b", getattr(om, "b_cell", None))):
                    if icell is None:
                        continue
                    b = m.blocks.get(icell)
                    if b == S:
                        print(f"    CLASH: {name}'s skin covers {other}.{iface} "
                              f"at {icell}")
        # count how many cells two modules both claim
        for i in range(len(mods)):
            for j in range(i + 1, len(mods)):
                (n1, m1), (n2, m2) = mods[i], mods[j]
                both = set(m1.blocks) & set(m2.blocks)
                conflict = [c for c in both if m1.blocks[c] != m2.blocks[c]]
                if conflict:
                    print(f"    OVERLAP {n1}/{n2}: {len(both)} shared cells, "
                          f"{len(conflict)} disagree, e.g. {sorted(conflict)[:3]}")
        print()


if __name__ == "__main__":
    main()
