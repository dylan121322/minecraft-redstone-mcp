"""
test_down_dirs.py — verify the DOWN tower in all four rotations.

Almost every bridge failure after switching the sink side to a down tower was a
"shaft conflict": the 2x2 footprint's partner row happened to be occupied. If the
shaft can be rotated, a blocked orientation is no longer fatal. This checks that
each (arm, side) combination still transfers the signal non-inverting.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import down_tower_cells_dir

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"

COMBOS = [((1, 0), (0, 1)), ((1, 0), (0, -1)),
          ((-1, 0), (0, 1)), ((-1, 0), (0, -1)),
          ((0, 1), (1, 0)), ((0, 1), (-1, 0)),
          ((0, -1), (1, 0)), ((0, -1), (-1, 0))]


def slab(B, x0, x1, z0, z1, y):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def run(arm, side, drive, cycles=2, base=0):
    y_top = base + 2 * cycles
    sc = nuc.Schematic.create(f"dd_{arm}_{side}_{drive}")
    B = sc.set_block_from_string
    slab(B, -10, 12, -10, 12, base - 3)
    ax, az = 3, 3
    # feed the top A dust from the west at y_top
    B(ax - 4, y_top, az, RB if drive else "minecraft:air")
    for xx in (ax - 4, ax - 3, ax - 2, ax - 1):
        B(xx, y_top - 1, az, S)
    B(ax - 3, y_top, az, W)
    B(ax - 2, y_top, az, repw())
    B(ax - 1, y_top, az, S)
    B(ax - 1, y_top + 1, az, W)
    B(ax, y_top, az, W)
    cells, foot = down_tower_cells_dir(ax, az, y_top, base, side=side, arm=arm)
    for (x, y, z, blk) in cells:
        B(x, y, z, blk)
    B(ax, base, az, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(60)
    return w.get_redstone_power(ax, base, az), sorted(foot)


if __name__ == "__main__":
    print("=== DOWN tower, all rotations (2 cycles = 4 torches, drop 4Y) ===")
    ok_all = True
    for arm, side in COMBOS:
        p1, foot = run(arm, side, 1)
        p0, _ = run(arm, side, 0)
        ok = (p1 > 0 and p0 == 0)
        ok_all &= ok
        print(f"  arm={arm} side={side}: drive1={p1} drive0={p0} "
              f"footprint={foot}  {'OK' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if ok_all else 'SOME FAIL'}")
