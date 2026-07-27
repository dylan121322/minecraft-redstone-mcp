"""
test_vertical.py — find a COMPACT vertical signal transmission (up AND down)
with minimal horizontal footprint, to replace the 4-wide staircase.

Candidates (MCHPRS):
  V1: repeater-via UP (already proven this session) — recap for baseline.
  V2: standing-torch tower UP — block, standing redstone_torch on top, that
      torch lights a dust one up-and-over; 2-wide zigzag. Compact-ish.
  V3: "glass/slab" tricks — skip; focus on torch tower + redstone.
  V4: DOWN transmission — dust naturally flows down a 1-wide staggered column?
      Test dust on stacked blocks stepping down in ONE horizontal cell (z), i.e.
      the descent uses +z instead of +x so it doesn't collide with x-neighbors.

Key idea for the router: if descent spreads in +Z (into the net's OWN reserved
approach column region) instead of +X, and each approach column owns a unique z
band, descents can't collide.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

def flr(B,x0,x1,z0,z1,y=-1):
    for x in range(x0,x1+1):
        for z in range(z0,z1+1): B(x,y,z,S)

def V4_descend_z(drive):
    """Descend y4->y0 spreading in +Z (not +X). y4 dust at (x,4,z0); step down
    one level per +z: block@(x,y2,z0+1)+dust@(x,y3,z0+1) ... lands y0 at z0+4.
    Same staircase but along Z. Verify it conducts."""
    sc=nuc.Schematic.create("v4"); B=sc.set_block_from_string
    flr(B,-2,4,-2,10)
    x=1; z0=1; b=0
    # drive a y4 dust at (x,b+4,z0) via a block riser
    B(x,b+3,z0,S); B(x,b+4,z0, RB if drive else W)
    if not drive: B(x,b+4,z0,W)
    # descend in +z
    B(x,b+2,z0+1,S); B(x,b+3,z0+1,W)
    B(x,b+1,z0+2,S); B(x,b+2,z0+2,W)
    B(x,b,  z0+3,S); B(x,b+1,z0+3,W)
    B(x,b,  z0+4,W)
    B(x,b,  z0+5,"minecraft:redstone_lamp")
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(24)
    return 1 if w.get_redstone_power(x,b,z0+4)>0 else 0, w.is_lit(x,b,z0+5)

def V2_tower_up(drive, torches):
    """Standing-torch tower going straight up, minimal footprint.
    Pattern per level: powered block -> standing torch on top (inverts) ->
    the torch powers the block above it -> next torch... Actually a standing
    torch on a block turns OFF when the block is powered. Stack:
      block0 (powered by input) -> torch1 on top (OFF when block0 powered)
      torch1 powers block1 above? standing torch powers the block ABOVE it.
    So: input=1 -> block0 powered -> torch1 off -> block1 unpowered -> ...
    Each torch inverts. Read top torch/block."""
    sc=nuc.Schematic.create("v2"); B=sc.set_block_from_string
    flr(B,-2,4,-2,4)
    x,z=1,1; b=0
    # reliable drive: redstone_block -> wire -> repeater(facing=west) -> block0
    B(x-3,b,z, RB if drive else "minecraft:air")
    B(x-2,b,z,W)
    B(x-1,b,z,"minecraft:repeater[facing=west,delay=1]")
    B(x,b,z,S)                      # block0, strongly powered by repeater from west
    y=b
    lit=[]
    for i in range(torches):
        # standing torch on top of current block
        B(x,y+1,z,"minecraft:redstone_torch")
        # block above the torch (torch powers block above it)
        B(x,y+2,z,S)
        lit.append((x,y+1,z))
        y+=2
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(24)
    return [1 if w.is_lit(*p) else 0 for p in lit]

if __name__=="__main__":
    print("V4 descend along +Z (compact, no x-spread):")
    for d in (0,1):
        p,l = V4_descend_z(d)
        print(f"  drive={d} -> y0_power={p} lamp={l} (expect power={d})  {'OK' if p==d else 'X'}")
    print("V2 standing-torch tower UP (each torch inverts):")
    for d in (0,1):
        seq = V2_tower_up(d, 3)
        print(f"  drive={d} -> torch lit seq (bottom..top)={seq}  (expect ~d,d,~d = {[1-d,d,1-d]})")
