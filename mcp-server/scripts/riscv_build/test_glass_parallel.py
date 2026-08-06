"""
test_glass_parallel.py — glass supports killed the see-below leak. Now test the
cases that actually block the router, to size how much the keep-out can shrink.

Cases (net A driven, net B read; B must never respond):
  G1 two lines on the SAME layer, 1 cell apart in z, both on glass
     (orthogonal dust-dust always couples — glass cannot help here)
  G2 two lines one layer apart, offset one cell (the see-below case) on glass
  G3 a line crossing OVER another: lower line on glass at y0, upper at y2 with a
     glass support at y1 directly above the lower wire
  G4 the gate-feed situation: two feeds at (x-1,z) and (x-1,z+2) on glass, with
     the middle cell (x-1,z+1) EMPTY — currently blocked because both feeds need
     that middle cell
  G5 same as G4 but the middle cell carries net A's wire on glass, i.e. can A
     pass right between the two feeds without touching B?
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
STONE = "minecraft:stone"; GLASS = "minecraft:glass"


def floor(B, y=-3, r=12):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, STONE)


def run(name, build, probes, ticks=25):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {p: w.get_redstone_power(*p) for p in probes}
    return out


def lineA(B, drive, z=0, y=0, sup=GLASS, x0=-4, x1=6):
    B(x0 - 1, y, z, RB if drive else "minecraft:air")
    B(x0 - 1, y - 1, z, STONE)
    for x in range(x0, x1 + 1):
        B(x, y - 1, z, sup)
        B(x, y, z, W)


def lineB(B, z=1, y=0, sup=GLASS, x0=-4, x1=6):
    for x in range(x0, x1 + 1):
        B(x, y - 1, z, sup)
        B(x, y, z, W)


def g1(B, drive):
    lineA(B, drive, z=0)
    lineB(B, z=1)


def g2(B, drive):
    lineA(B, drive, z=0, y=0)
    lineB(B, z=1, y=-1)          # one layer down, one cell across


def g3(B, drive):
    lineA(B, drive, z=0, y=0)
    # upper crossing line at y=2 supported by glass at y=1 over the lower wire
    for z in range(-3, 4):
        B(1, 1, z, GLASS)
        B(1, 2, z, W)


def g4(B, drive):
    """two feed cells 2 apart in z on glass, middle cell empty."""
    lineA(B, drive, z=0, x1=2)
    lineB(B, z=2, x0=-4, x1=2)


def g5(B, drive):
    """net A additionally runs THROUGH the middle row z=1 on glass."""
    lineA(B, drive, z=0, x1=2)
    for x in range(-4, 3):
        B(x, -1, 1, GLASS)
        B(x, 0, 1, W)            # A's own wire in the middle row
    lineB(B, z=2, x0=-4, x1=2)


if __name__ == "__main__":
    print("G1 same layer, 1 apart in z (glass supports):")
    print(f"   {run('g1', g1, [(6, 0, 1)])}")
    print("G2 one layer down, one across (see-below) on glass:")
    print(f"   {run('g2', g2, [(6, -1, 1)])}")
    print("G3 crossing over on glass (upper at y=2):")
    print(f"   {run('g3', g3, [(1, 2, 3)])}")
    print("G4 two feeds 2 apart in z, middle empty:")
    print(f"   {run('g4', g4, [(2, 0, 2)])}")
    print("G5 A passes through the middle row between the two feeds:")
    print(f"   {run('g5', g5, [(2, 0, 2)])}")
    print("\nA probe that changes with drive = the nets couple.")
