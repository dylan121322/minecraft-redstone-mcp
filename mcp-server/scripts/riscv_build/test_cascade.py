"""
test_cascade.py — TrunkBox -> Connector -> DeliveryBox, all shielded modules.

Each module already passes on its own, sealed and with hostile geometry against its
shell. What failed was the joint between them, wired by the caller. Now the joint is
a module too, so the whole path is modules end to end and there is nothing left for
a caller to get wrong.

Judged strictly in both directions, and repeated with hostile geometry pressed
against every shell, because the point of the shells is that a bench result carries
over into a real module.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from trunk_box import TrunkBox
from delivery_box import DeliveryBox, TowerBox
from connector import Connector

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def run_chain(mods, drive, hostile=False, base_y=0, ticks=140):
    sc = nuc.Schematic.create("casc")
    B = sc.set_block_from_string
    xs, ys, zs = [], [], []
    for m in mods:
        (x0, y0, z0), (x1, y1, z1) = m.extent
        xs += [x0, x1]; ys += [y0, y1]; zs += [z0, z1]
    for x in range(min(xs) - 8, max(xs) + 10):
        for z in range(min(zs) - 6, max(zs) + 8):
            B(x, base_y - 1, z, S)
    for m in mods:
        for (x, y, z), blk in m.blocks.items():
            B(x, y, z, blk)

    ix, iy, iz = mods[0].in_cell
    B(ix - 2, iy, iz, RB if drive else "minecraft:air")
    B(ix - 1, iy, iz, W)

    ox, oy, oz = mods[-1].out_cell
    B(ox + 1, oy, oz, W)
    B(ox + 2, oy, oz, repw())
    B(ox + 3, oy, oz, W)

    if hostile:
        for m in mods:
            (x0, y0, z0), (x1, y1, z1) = m.extent
            for z in (z0 - 1, z1 + 1):
                for x in range(x0, x1 + 1, 3):
                    B(x, base_y, z, W)
                    B(x, base_y, z + (1 if z > z1 else -1), RB)

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return (w.get_redstone_power(*mods[-1].out_cell),
            w.get_redstone_power(ox + 3, oy, oz))


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
    # hand the connector both neighbours' cells so its skin cannot overwrite them
    cn = Connector(a_out=tb.out_cell, b_in=db.in_cell,
                   b_is_repeater=True,                 # module inputs are repeaters
                   keep_out=frozenset(tb.blocks) | frozenset(db.blocks))
    return tb, cn, db


if __name__ == "__main__":
    print("=== TrunkBox -> Connector -> DeliveryBox (all modules) ===")
    ok = True
    for plane, run_to, row, sink_x in ((5, 60, 30, 120),
                                       (5, 150, 45, 260),
                                       (9, 100, 40, 200),
                                       (13, 200, 60, 320)):
        tb, cn, db = build(plane, run_to, row, sink_x)
        mods = [tb, cn, db]
        total = sum(len(m.blocks) for m in mods)
        o1, p1 = run_chain(mods, 1)
        o0, _ = run_chain(mods, 0)
        h1, _ = run_chain(mods, 1, hostile=True)
        h0, _ = run_chain(mods, 0, hostile=True)
        clean = (o1 > 0 and o0 == 0)
        shield = (h1 > 0 and h0 == 0)
        ok &= clean and shield
        print(f"  plane={plane:2d} run_to={run_to:3d} row={row:2d} sink_x={sink_x:3d}"
              f"  conn_len={cn.length:3d} blocks={total:5d}")
        print(f"      clean   drive1 out={o1:2d} pin={p1:2d} | drive0 out={o0:2d}"
              f"   {'OK' if clean else 'FAIL'}")
        print(f"      hostile drive1 out={h1:2d} | drive0 out={h0:2d}"
              f"   {'SHIELDED' if shield else 'LEAKS'}")
    print(f"  => {'ALL OK' if ok else 'SOME FAIL'}")
