"""
test_glass_seam.py — the isolated structure tests all passed on glass (plain runs,
tower tops, repeaters on supports), no wall-torch mount or standing torch landed
on glass, yet the full circuit got worse. So the break is at a SEAM between a
glass-supported section and a stone-supported one.

The suspect: a descent staircase (whose own supports stay stone) hands off FROM a
cross run whose supports are now glass. The first stair step reads the cross dust
above/beside it, and that hand-off may need the cross support to be powerable.

Build the exact seam both ways and compare:
  cross run on X supports -> stair top -> descent to y0 -> read the landing
with X = stone (old behaviour) and X = glass (new behaviour).
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
STONE = "minecraft:stone"; GLASS = "minecraft:glass"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-2, r=16):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, STONE)


def build(B, drive, cross_sup, stair_sup, cy=5):
    """A cross run at height cy on `cross_sup`, then a staircase down to y=0
    whose own supports are `stair_sup`, then a landing dust."""
    # driver into the cross run
    B(-6, cy, 0, RB if drive else "minecraft:air")
    B(-6, cy - 1, 0, STONE)
    for x in range(-5, 1):
        B(x, cy - 1, 0, cross_sup)
        B(x, cy, 0, W)
    # staircase: one x-step per level down from cy to 0
    x = 0
    y = cy
    while y > 0:
        x += 1
        y -= 1
        if y > 0:
            B(x, y - 1, 0, stair_sup)
        B(x, y, 0, W)
    return (x, 0, 0)


def run(cross_sup, stair_sup, cy=5, ticks=40):
    out = {}
    land = None
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"seam_{cross_sup[-5:]}_{stair_sup[-5:]}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        land = build(B, drive, cross_sup, stair_sup, cy)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = w.get_redstone_power(*land)
    return out, land


if __name__ == "__main__":
    print(f"{'cross_sup':8s} {'stair_sup':10s} {'landing':>12s}  verdict")
    print("-" * 52)
    for cs in (STONE, GLASS):
        for ss in (STONE, GLASS):
            r, land = run(cs, ss)
            tag = f"{r[0]}->{r[1]}"
            ok = r[1] > 0 and r[0] == 0
            print(f"{cs.split(':')[1]:8s} {ss.split(':')[1]:10s} {tag:>12s}  "
                  f"{'OK' if ok else 'BROKEN'}")
    print("\nIf (glass, stone) is broken while (stone, stone) works, the seam")
    print("between a glass cross run and a stone staircase is the regression.")
