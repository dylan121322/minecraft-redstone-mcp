"""
diag_cascade.py — walk a TrunkBox->Connector->DeliveryBox chain cell by cell in
MCHPRS and report the power at every stage, so the break point is a fact.

Small world (a few thousand blocks), runs on the Mac in seconds.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from trunk_box import TrunkBox
from delivery_box import DeliveryBox, TowerBox
from connector import Connector

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def main():
    plane, run_to, row, sink_x = 5, 60, 30, 120
    base_y = 0
    tb = TrunkBox(src_cell=(0, base_y, 10), plane=plane,
                  run_to_x=run_to, leg_to_z=row)
    db = DeliveryBox(anchor=(sink_x - 2 - (plane - base_y), plane, row),
                     drop=plane - base_y)
    cn = Connector(a_out=tb.out_cell, b_in=db.in_cell,
                   keep_out=frozenset(tb.blocks) | frozenset(db.blocks))

    sc = nuc.Schematic.create("dc")
    B = sc.set_block_from_string
    for m in (tb, cn, db):
        (x0, y0, z0), (x1, y1, z1) = m.extent
        for x in range(x0 - 6, x1 + 8):
            for z in range(z0 - 4, z1 + 6):
                B(x, base_y - 1, z, S)
        for (x, y, z), blk in m.blocks.items():
            B(x, y, z, blk)

    import sys as _sys
    drive = int(_sys.argv[1]) if len(_sys.argv) > 1 else 1
    ix, iy, iz = tb.in_cell
    B(ix - 2, iy, iz, RB if drive else "minecraft:air")
    B(ix - 1, iy, iz, W)

    # read the delivery out through a pin
    ox, oy, oz = db.out_cell
    B(ox + 1, oy, oz, W)
    B(ox + 2, oy, oz, repw())
    B(ox + 3, oy, oz, W)

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(140)

    def show(label, pos):
        print(f"  {label:28s} {pos}  pow={w.get_redstone_power(*pos)}")

    show("tb.in", tb.in_cell)
    show("tb climb top (plane)", (0 + 2, plane, 10))
    show("tb.out", tb.out_cell)
    # walk the connector
    ax, ay, az = cn.a_cell
    bx, by, bz = cn.b_cell
    show("conn.a", cn.a_cell)
    # connector path along x then z
    stepx = 1 if bx > ax else -1
    for x in range(ax + stepx, bx + stepx, stepx):
        if (x, ay, az) in cn.blocks:
            show(f"conn x={x}", (x, ay, az))
    stepz = 1 if bz > az else -1
    for z in range(az + stepz, bz + stepz, stepz):
        if (bx, ay, z) in cn.blocks:
            show(f"conn z={z}", (bx, ay, z))
    show("conn.b / deliv.in", cn.b_cell)
    show("deliv.out", db.out_cell)
    show("pin out", (ox + 3, oy, oz))


if __name__ == "__main__":
    main()
