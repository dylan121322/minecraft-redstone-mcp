"""
test_torch_tower.py — MCHPRS: verify a COMPACT vertical redstone signal tower
to replace the +x staircase (which spans 4 in x and creates shared y2/y3
intermediate dust => the 11 residual shorts).

Goal: a ~1x2 footprint vertical column that carries a signal UP (and DOWN) many
Y-levels without horizontal spread, so different nets' towers only need to be
spaced apart in the plane (no x-staircase overlap).

Classic Minecraft vertical transmission = "torch ladder": a column of solid
blocks, with a redstone_wall_torch on alternating faces of each block. Each
torch inverts, so 2 blocks = 1 non-inverted step up. Signal climbs the ladder.

Test T1: torch ladder UP — drive bottom, read top, several heights.
Test T2: two adjacent ladders (different nets) — isolation.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

def floor(B,x0,x1,z0,z1,y=-1):
    for x in range(x0,x1+1):
        for z in range(z0,z1+1): B(x,y,z,S)

def T1(drive):
    """Torch ladder climbing in +y at column (2,z=2). Standard staggered-block
    ladder: block+torch alternating so signal steps up 1 block per torch pair."""
    sc=nuc.Schematic.create("t1"); B=sc.set_block_from_string
    floor(B,-2,8,-2,8)
    x,z=2,2
    # input dust at (x,0,z) driven from west block at (x-1,0,z)
    B(x-1,0,z, RB if drive else W)
    if not drive: B(x-1,0,z,W)
    B(x,0,z,W)
    # ladder: the canonical vertical staircase uses blocks offset in one horiz
    # dir with a torch under each next block. Build a 2-wide staggered climb:
    #   block@(x,0,z) is fed; torch on its top? torches on TOP = standing torch.
    # Use standing torches stacked with blocks (the "redstone ladder"):
    #   B0 at (x,0,z) powered -> standing torch on top OFF... that inverts.
    # For NON-inverting climb, use 2 torches. Build 4 levels:
    lvl_probe=[]
    cx=x
    for i in range(4):
        # place a block, standing torch on top, next block on the torch's... no.
        pass
    # Simpler verified vertical: alternating wall torches on a block column.
    # Column of blocks at (x, y, z) for y=1..5; wall torch on the SOUTH face
    # (facing=south) at each level pointing to a dust that goes up.
    # This is fiddly; instead test the KNOWN-GOOD stacked torch tower:
    #   (x,0,z) input dust -> (x,0,z) also has block above?
    # Canonical: torch tower = redstone_torch on block, dust on block beside top,
    # torch on that, repeat. 2-wide.
    A=x; Bx=x+1
    # level 0
    B(A,0,z,W)                       # input
    B(A,1,z,S)                       # block above input (gets powered by dust below? no)
    # Use the proven "block + standing torch" inverter chain going up in a 2-col zigzag:
    # col A: torch on top of a powered block lights the block/dust above-beside
    # Give up on hand-deriving; measure the simplest that works below in T1b.
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(20)
    return None

def T1b(drive, levels=3):
    """Zigzag torch tower (verified pattern): alternating columns A(x) and B(x+1).
    Signal goes up via: dust on block -> torch on side lights dust above on the
    OTHER column -> torch again -> ... Each torch = +1 level, inverts, so `levels`
    torches invert `levels` times. Read top; expected = drive XOR (levels odd)."""
    sc=nuc.Schematic.create("t1b"); B=sc.set_block_from_string
    floor(B,-2,10,-2,6)
    A=2; z=2
    # base: driven dust feeds a block; torch on that block's face lights dust above
    B(A-1,0,z, RB if drive else W)
    if not drive: B(A-1,0,z,W)
    B(A,0,z,S)                            # base block, powered by input dust to its west
    # wall torch on EAST face of base block, at y=1 -> lights when base UNpowered
    B(A+1,1,z, wt("east"))                # torch sticks out east, one level up
    B(A+1,2,z,S)                          # block above torch (torch powers it)
    B(A,3,z, wt("west"))                  # next torch on west face one higher
    B(A,4,z,S)
    top=(A,4,z)
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(20)
    return 1 if w.is_lit(A+1,1,z) else 0, 1 if w.is_lit(A,3,z) else 0

if __name__=="__main__":
    print("T1b torch tower (2 torches = 2 inversions):")
    for d in (0,1):
        t1,t2 = T1b(d)
        print(f"  drive={d}: torch1_lit={t1} torch2_lit={t2}  (torch1=~drive, torch2=~torch1=drive)")
