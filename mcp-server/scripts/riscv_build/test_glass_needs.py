"""
test_glass_needs.py — glass supports isolate the see-below coupling but broke the
circuit (16/40 -> 10/40) whether or not the floor stayed stone. So some supports
are load-bearing electrically. Find out WHICH structures still need a powerable
block underneath:

  S1 a plain horizontal run: does a glass support carry it?          (expect yes)
  S2 a descent staircase step: dust at (x,y) on support (x,y-1), next step
     (x+1,y-1) on (x+1,y-2). Does the diagonal step still conduct on glass?
  S3 the tower top hand-off: last tower block, dust above it, cross run leaving
  S4 a repeater sitting on glass (refresh repeaters are placed on supports)
  S5 dust -> block -> torch chain (the gate's own inverter) on glass
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
STONE = "minecraft:stone"; GLASS = "minecraft:glass"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-4, r=14):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, STONE)


def run(name, build, probe, sup, ticks=30):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        build(B, drive, sup)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = w.get_redstone_power(*probe)
    return out


def s1(B, drive, sup):
    """plain raised run at y=2 on `sup`."""
    B(-4, 2, 0, RB if drive else "minecraft:air"); B(-4, 1, 0, STONE)
    for x in range(-3, 5):
        B(x, 1, 0, sup); B(x, 2, 0, W)


def s2(B, drive, sup):
    """descent staircase: y=4 down to y=0, one x-step per level, supports `sup`."""
    B(-4, 4, 0, RB if drive else "minecraft:air"); B(-4, 3, 0, STONE)
    B(-3, 3, 0, sup); B(-3, 4, 0, W)
    y = 4
    x = -3
    while y > 0:
        x += 1; y -= 1
        B(x, y - 1, 0, sup)
        B(x, y, 0, W)


def s3(B, drive, sup):
    """tower top: stone rungs, then a cross run on `sup` leaving the top dust."""
    B(-4, 0, 0, RB if drive else "minecraft:air"); B(-4, -1, 0, STONE)
    B(-3, 0, 0, W); B(-3, -1, 0, STONE)
    B(-2, 0, 0, rep("west")); B(-2, -1, 0, STONE)
    B(-1, 0, 0, STONE)                       # tower base (must be stone)
    y = 0
    for _ in range(2):
        B(-1, y + 1, 0, "minecraft:redstone_torch")
        B(-1, y + 2, 0, STONE)
        y += 2
    B(-1, y + 1, 0, W)                       # top dust
    for x in range(0, 6):                    # cross run on `sup`
        B(x, y, 0, sup); B(x, y + 1, 0, W)


def s4(B, drive, sup):
    """a refresh repeater standing on `sup`."""
    B(-4, 2, 0, RB if drive else "minecraft:air"); B(-4, 1, 0, STONE)
    for x in range(-3, 0):
        B(x, 1, 0, sup); B(x, 2, 0, W)
    B(0, 1, 0, sup); B(0, 2, 0, rep("west"))
    for x in range(1, 5):
        B(x, 1, 0, sup); B(x, 2, 0, W)


def s5(B, drive, sup):
    """dust -> mount -> wall torch, with the mount ON `sup`."""
    B(-4, 2, 0, RB if drive else "minecraft:air"); B(-4, 1, 0, STONE)
    for x in range(-3, 0):
        B(x, 1, 0, sup); B(x, 2, 0, W)
    B(0, 1, 0, sup); B(0, 2, 0, STONE)       # the mount itself stays stone
    B(1, 2, 0, wt("east"))
    B(2, 1, 0, sup); B(2, 2, 0, W)


CASES = [("S1 plain raised run", s1, (4, 2, 0)),
         ("S2 descent staircase", s2, (1, 0, 0)),
         ("S3 tower top + cross", s3, (5, 5, 0)),
         ("S4 repeater on support", s4, (4, 2, 0)),
         ("S5 mount + wall torch", s5, (2, 2, 0))]

if __name__ == "__main__":
    print(f"{'case':26s} {'stone':>14s} {'glass':>14s}  verdict")
    print("-" * 76)
    for name, fn, probe in CASES:
        try:
            rs = run(name, fn, probe, STONE)
            rg = run(name, fn, probe, GLASS)
        except Exception as e:
            print(f"{name:26s} ERROR {type(e).__name__}: {str(e)[:30]}")
            continue
        ws = f"{rs[0]}->{rs[1]}"
        wg = f"{rg[0]}->{rg[1]}"
        stone_ok = rs[1] > 0
        glass_ok = rg[1] > 0
        verdict = ("glass FINE" if glass_ok and stone_ok else
                   "glass BREAKS it" if stone_ok and not glass_ok else
                   "broken on both")
        print(f"{name:26s} {ws:>14s} {wg:>14s}  {verdict}")
