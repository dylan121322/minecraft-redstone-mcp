"""
test_underground_chain.py — plan 2: put the trunk corridor UNDERGROUND so the sink
side climbs with the 1x1 UP tower, whose non-inverting behaviour is measured, and
drop the 2x2 DOWN tower from the delivery path entirely.

Why: the DOWN tower turned out to be CONSISTENTLY inverting (8/10/12 torches all
inverted), which contradicts the earlier "even torch count is non-inverting"
reading. That earlier test drove the tower's top dust directly; in real use the
top is driven through a repeater, and the effective inversion count is odd. The UP
tower, by contrast, was verified four ways in test_via_tower.

Chain under test:
    y0 source dust -> repeater -> DOWN staircase to the underground plane
    -> underground trunk (refresh every 12) -> 1x1 UP tower -> y0 feed cell
    -> gate input pin (repeater facing west)

Judged strictly: drive1 must give power at the feed AND drive0 must give zero.
(The earlier end-to-end test only checked that drive1 was high, which is how an
inverting delivery slipped through.)
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import up_tower_cells, trunk_cells

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def run(drive, length, depth=8, pin_x=None, z=4):
    """depth = how far below y0 the trunk runs.

    The UP tower's readable dust sits at y_top+1, so landing it on the base plane
    needs y_top = base-1 and hence span = depth-1. A non-inverting climb needs the
    torch count (span/2) to be even, i.e. span divisible by 4 — so depth must be
    4k+1 (5, 9, 13, ...), an ODD depth."""
    base = 0
    ty = base - depth
    pin_x = pin_x if pin_x is not None else length + 6
    sc = nuc.Schematic.create(f"ug_{drive}_{length}")
    B = sc.set_block_from_string
    # The module floor at base-1 must NOT be laid where the staircase passes
    # through it, otherwise the slab isolates the descent (measured: the run died
    # on its third step, exactly where it crossed y=base-1).
    stair_cols = set(range(-1, -1 + depth + 1))
    for x in range(-8, pin_x + 8):
        for zz in range(-4, z + 8):
            B(x, ty - 2, zz, S)          # floor under the underground plane
            if not (x in stair_cols and zz == z):
                B(x, base - 1, zz, S)    # the module's own floor

    # source at y0 -> repeater -> staircase down to the trunk plane
    B(-4, base, z, RB if drive else "minecraft:air")
    B(-3, base, z, W)
    B(-2, base, z, repw())
    x = -1
    y = base
    while y > ty:
        B(x, y - 1, z, S)
        B(x, y, z, W)
        x += 1
        y -= 1
    B(x, ty, z, W)

    # underground trunk
    tr, _ = trunk_cells(z, x, x + length, ty)
    for (bx, by, bz, blk) in tr:
        B(bx, by, bz, blk)
    shaft = x + length

    # 1x1 UP tower from the trunk plane back to y0.
    # up_tower_cells(ax, az, y_bot, y_top) puts its readable dust at y_top+1, so
    # y_top = base-1 lands the dust exactly on the base plane.
    up, _ = up_tower_cells(shaft + 1, z, ty, base - 1)
    for (bx, by, bz, blk) in up:
        B(bx, by, bz, blk)
    # the tower needs its base block driven: repeater on the trunk feeding it
    B(shaft, ty, z, repw())

    feed = shaft + 1
    for xx in range(feed + 1, pin_x):
        B(xx, base, z, W)
    B(pin_x, base, z, repw())            # gate input pin
    B(pin_x + 1, base, z, W)             # pin output

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(90)
    return (w.get_redstone_power(feed, base, z),
            w.get_redstone_power(pin_x + 1, base, z))


if __name__ == "__main__":
    print("=== underground trunk + UP-tower sink delivery ===")
    print("strict: drive1 feed>0 AND drive0 feed==0")
    allok = True
    for depth in (5, 9, 13):
        for length in (20, 80, 200):
            f1, o1 = run(1, length, depth)
            f0, o0 = run(0, length, depth)
            ok = f1 > 0 and f0 == 0
            allok &= ok
            print(f"  depth={depth:2d} trunk={length:3d}: "
                  f"drive1 feed={f1:2d} pin_out={o1:2d} | "
                  f"drive0 feed={f0:2d} pin_out={o0:2d}   "
                  f"{'OK' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")
