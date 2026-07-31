"""
test_sink_fixed.py — sink delivery with the inversion compensated.

The 2x2 DOWN tower inverts unconditionally, so the delivery path is:
    trunk dust -> parity bridge -> DOWN tower -> INVERTER -> feed cell -> gate pin

The inverter (via_gadget.inverter_cells, variant I1) was measured standalone:
drive high -> 0, drive low -> 15, and it drives a west-facing pin. This checks the
composition, judged strictly in both directions — the flaw in the earlier
end-to-end test was accepting "drive1 is high" without confirming drive0 is 0.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import down_tower_cells_dir, inverter_cells

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"

ROTS = [((0, 1), (1, 0)), ((0, -1), (1, 0)),
        ((1, 0), (0, 1)), ((1, 0), (0, -1))]


def run(arm, side, drive, trunk_y=9, z=4):
    """Shaft at x=10; tower drops to y0; inverter; then the pin."""
    base = 0
    shaft = 10
    sc = nuc.Schematic.create(f"sf_{arm}_{side}_{drive}")
    B = sc.set_block_from_string
    for x in range(-6, shaft + 24):
        for zz in range(-4, z + 8):
            B(x, base - 1, zz, S)

    # trunk feeding the shaft
    for x in range(shaft - 6, shaft - 3):
        B(x, trunk_y - 1, z, S)
    B(shaft - 6, trunk_y, z, RB if drive else "minecraft:air")
    B(shaft - 5, trunk_y, z, W)
    B(shaft - 4, trunk_y, z, repw())
    for x in range(shaft - 3, shaft + 1):
        B(x, trunk_y - 1, z, S)
        B(x, trunk_y, z, W)

    # parity bridge to an even span, then the tower
    dn_from = trunk_y
    if (dn_from - base) % 2:
        B(shaft, dn_from - 2, z, S)
        B(shaft, dn_from - 1, z, W)
        dn_from -= 1
    cells, _foot = down_tower_cells_dir(shaft, z, dn_from, base, side=side, arm=arm)
    for (x, y, zz, b) in cells:
        B(x, y, zz, b)

    # the tower's bottom dust is at (shaft, base, z); invert from there going east
    inv, out = inverter_cells(shaft, base, z, direction=(1, 0))
    for (x, y, zz, b) in inv:
        B(x, y, zz, b)

    # output dust runs east into the pin
    pin_x = out[0] + 3
    for x in range(out[0] + 1, pin_x):
        B(x, base, z, W)
    B(pin_x, base, z, repw())
    B(pin_x + 1, base, z, W)

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)
    return (w.get_redstone_power(shaft, base, z),   # tower bottom (inverted)
            w.get_redstone_power(*out),             # after the inverter
            w.get_redstone_power(pin_x + 1, base, z))


if __name__ == "__main__":
    print("=== DOWN tower + inverter, strict both ways ===")
    allok = True
    for arm, side in ROTS:
        t1, o1, p1 = run(arm, side, 1)
        t0, o0, p0 = run(arm, side, 0)
        ok = (o1 > 0 and o0 == 0)
        allok &= ok
        print(f"  arm={arm} side={side}")
        print(f"     drive1: tower_bottom={t1:2d} after_inv={o1:2d} after_pin={p1:2d}")
        print(f"     drive0: tower_bottom={t0:2d} after_inv={o0:2d} after_pin={p0:2d}")
        print(f"     {'OK (non-inverting overall)' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")
