"""
test_underground.py — feasibility of moving the cross plane BELOW the signal
plane so the sink side becomes a CLIMB instead of a descent.

Why: every remaining unrouted net fails with "DESCENT conflict". A descent is a
staircase that eats `depth` cells of horizontal room right where the sink sits,
and those lanes get taken by nets routed earlier. A CLIMB, by contrast, is the
verified 1x1 torch tower — zero horizontal spread. If the cross plane lives
underground, the sink side climbs up into the pin and the whole descent-conflict
class disappears.

Geometry under test:
  y=0   : signal plane (gate cells, pins, local wiring) + a stone floor at y=-1
  y=-3  : underground cross plane (dust on supports at y=-4)
  source: y0 -> dust drops into the ground? A DOWN transfer is still needed on
          the SOURCE side. But sources are NOT the bottleneck (0 starved sources
          after the placer fix) and a source can afford a staircase because it
          starts in open ground east of its cell.
  sink  : underground dust -> 1x1 torch tower climbing to y0 -> feeds pin west cell

Tests:
  U1: does a dust run work at y=-3 under a solid y=-1 floor (no interaction)?
  U2: 1x1 torch tower from y=-3 up to y0, non-inverting, landing on a y0 dust
      that then feeds a west-facing repeater (the gate input pin).
  U3: isolation — an underground run directly below a y0 run of another net.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def slab(B, x0, x1, z0, z1, y):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def U1(drive, length=12):
    """Dust run at y=-3 (supports y=-4), with the normal y=-1 floor above it."""
    sc = nuc.Schematic.create(f"u1_{drive}"); B = sc.set_block_from_string
    slab(B, -4, 24, -2, 4, -1)          # the module's normal floor
    slab(B, -4, 24, -2, 4, -4)          # supports for the underground plane
    B(-2, -3, 0, RB if drive else "minecraft:air")
    for x in range(-1, length):
        B(x, -3, 0, W)
    end = (length - 1, -3, 0)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(30)
    return w.get_redstone_power(*end)


def U2(drive, depth=3):
    """Underground dust at y=-depth climbs a 1x1 torch tower to y0 and feeds a
    west-facing repeater (a gate input pin) via the pin's west cell."""
    sc = nuc.Schematic.create(f"u2_{drive}_{depth}"); B = sc.set_block_from_string
    slab(B, -6, 20, -2, 4, -depth - 1)
    # underground feed: RB -> dust -> repeater -> tower base block
    B(0, -depth, 0, RB if drive else "minecraft:air")
    B(1, -depth, 0, W)
    B(2, -depth, 0, repw())              # drives east into the tower base
    tx = 3
    B(tx, -depth, 0, S)                   # block0
    y = -depth
    n = 0
    while y + 2 <= 0:                     # climb to y0 with (torch, block) pairs
        B(tx, y + 1, 0, TORCH)
        B(tx, y + 2, 0, S)
        y += 2; n += 1
    # top dust one above the last block; that is the cell feeding the pin
    feed_y = y + 1
    B(tx, feed_y, 0, W)
    # the gate input pin sits east of the feed cell at the same height
    B(tx + 1, feed_y, 0, repw())
    B(tx + 2, feed_y, 0, W)               # pin output (what the gate would drive)
    B(tx + 2, feed_y, 1, LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(40)
    return (n, feed_y,
            w.get_redstone_power(tx, feed_y, 0),
            w.get_redstone_power(tx + 2, feed_y, 0))


def U3(drive_under, drive_over):
    """Underground run at y=-3 directly beneath a y0 run of a DIFFERENT net —
    are they isolated by the floor?"""
    sc = nuc.Schematic.create(f"u3_{drive_under}{drive_over}"); B = sc.set_block_from_string
    slab(B, -4, 20, -2, 4, -1)
    slab(B, -4, 20, -2, 4, -4)
    # underground net
    B(-2, -3, 0, RB if drive_under else "minecraft:air")
    for x in range(-1, 12):
        B(x, -3, 0, W)
    # surface net directly above
    B(-2, 0, 0, RB if drive_over else "minecraft:air")
    for x in range(-1, 12):
        B(x, 0, 0, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(30)
    return w.get_redstone_power(11, -3, 0), w.get_redstone_power(11, 0, 0)


if __name__ == "__main__":
    print("=== U1: dust run on an underground plane (y=-3) ===")
    for d in (0, 1):
        print(f"  drive={d}: end power={U1(d)}")

    print("\n=== U2: 1x1 climb from underground into a y0 gate input pin ===")
    for depth in (3, 5, 7):
        for d in (0, 1):
            n, fy, feed, pin_out = U2(d, depth)
            print(f"  depth={depth} ({n} torches, feed_y={fy}) drive={d}: "
                  f"feed={feed} pin_out={pin_out}")

    print("\n=== U3: isolation between an underground run and a y0 run above ===")
    for du in (0, 1):
        for do in (0, 1):
            u, o = U3(du, do)
            print(f"  under={du} over={do}: under_end={u} over_end={o}")
