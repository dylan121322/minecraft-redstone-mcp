"""
test_vertical_dust.py — confirm the suspected break in the down-tower input.

MCHPRS trace of the failing sink showed:
    dy=+2 (y=9, the cross plane) : W15   <- powered
    dy=+1 (y=8)                  : #0    <- a BLOCK sits here
    dy=+0 (y=7 down to y0)       : 0     <- everything below is dead

_pick_down_tower sets y_from = cy_cross and puts a `pre` dust at
(feed, cy_cross), while the cross run's dust lives at cy_cross+1. So the intended
hand-off is cross-dust(y+1) -> pre-dust(y) in the SAME column, i.e. two dusts
stacked vertically. Physics case P4 measured that a dust directly above another,
with no support block between, does NOT couple.

Test the three plausible hand-offs so the fix is chosen from measurement:
  V1 dust directly above dust (what the code builds)
  V2 dust above, block between (dust -> block -> dust below: strong power)
  V3 stair step: cross dust at (x, y+1), pre dust at (x+1, y) — the see-below
     geometry that P6 measured as COUPLED
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"


def flat(B, y, r=8):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def run(name, build, probe, ticks=30):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        flat(B, -1)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = w.get_redstone_power(*probe)
    return out


def v1(B, drive):
    """dust directly above dust — what _pick_down_tower currently relies on."""
    # upper line at y=2 on supports, driven
    for x in range(-4, 2):
        B(x, 1, 0, S); B(x, 2, 0, W)
    B(-5, 2, 0, RB if drive else "minecraft:air"); B(-5, 1, 0, S)
    # the 'pre' dust one level lower, SAME column as the upper line's end
    B(1, 0, 0, S)          # support for the lower dust
    B(1, 1, 0, W)          # lower dust, directly under the upper dust at (1,2,0)


def v2(B, drive):
    """dust -> block -> dust below (strong power through the block)."""
    for x in range(-4, 1):
        B(x, 1, 0, S); B(x, 2, 0, W)
    B(-5, 2, 0, RB if drive else "minecraft:air"); B(-5, 1, 0, S)
    B(1, 2, 0, S)          # block at the end of the upper line
    B(1, 1, 0, W)          # dust below that block? needs its own support
    B(1, 0, 0, S)


def v3(B, drive):
    """see-below stair: upper dust at (0,2), lower dust one across at (1,1)."""
    for x in range(-4, 1):
        B(x, 1, 0, S); B(x, 2, 0, W)
    B(-5, 2, 0, RB if drive else "minecraft:air"); B(-5, 1, 0, S)
    B(1, 0, 0, S)          # support
    B(1, 1, 0, W)          # lower dust, one cell EAST and one DOWN


if __name__ == "__main__":
    print("V1 dust directly above dust (current code):")
    print(f"   {run('v1', v1, (1, 1, 0))}")
    print("V2 dust -> block -> dust below:")
    print(f"   {run('v2', v2, (1, 1, 0))}")
    print("V3 see-below stair (one across, one down):")
    print(f"   {run('v3', v3, (1, 1, 0))}")
    print("\nA value that changes with drive means the hand-off conducts.")
