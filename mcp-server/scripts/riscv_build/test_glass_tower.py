"""
test_glass_tower.py — glass supports are incompatible with the STAIRCASE descent:
the stair's first step reads the cross dust through the support's strong power, and
glass cannot be powered, so any glass in the cross run kills the stair (measured:
(glass cross, stone stair) -> landing 0, while (stone, stone) -> 5).

But the 2x2 DOWN TOWER does not use see-below at all — it hands the signal down
through wall torches, which read their own mount. So the combination that should
work is:

    glass passive supports  +  down-tower descent (no staircase)

Test it end to end: a cross run on GLASS supports feeding a down tower that lands
on y0. Compare with stone supports as the control.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import down_tower_cells_dir

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
STONE = "minecraft:stone"; GLASS = "minecraft:glass"


def floor(B, y=-2, r=16):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, STONE)


def build(B, drive, cross_sup, cy=4, arm=(0, 1), side=(-1, 0)):
    """cross run at cy+1 on `cross_sup`, then a down tower from cy to y0 at x=0."""
    B(-7, cy + 1, 0, RB if drive else "minecraft:air")
    B(-7, cy, 0, STONE)
    for x in range(-6, 0):
        B(x, cy, 0, cross_sup)
        B(x, cy + 1, 0, W)
    # the tower's input dust one level below the cross plane, in the tower column
    B(0, cy, 0, W)
    B(0, cy - 1, 0, cross_sup)
    cells, foot = down_tower_cells_dir(0, 0, cy, 0, side=side, arm=arm)
    for (x, y, z, blk) in cells:
        B(x, y, z, blk)
    B(0, 0, 0, W)
    return (0, 0, 0)


def run(cross_sup, cy=4, ticks=40, arm=(0, 1), side=(-1, 0)):
    out = {}
    land = None
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"gt_{cross_sup[-5:]}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        land = build(B, drive, cross_sup, cy, arm, side)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = w.get_redstone_power(*land)
    return out, land


if __name__ == "__main__":
    print("glass supports + DOWN TOWER (no staircase):")
    for cs in (STONE, GLASS):
        for cy in (4, 8):
            r, land = run(cs, cy)
            ok = r[1] > 0 and r[0] == 0
            print(f"  cross_sup={cs.split(':')[1]:6s} cy={cy}: "
                  f"landing {r[0]}->{r[1]}  {'OK' if ok else 'BROKEN'}")
    print("\nIf glass works here, the fix is: glass supports everywhere AND")
    print("deliver every bridged sink with a down tower instead of a staircase.")
