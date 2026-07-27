"""
test_tower_down.py — MCHPRS: verify a 1x1-footprint VERTICAL DOWN signal
transmission (y5 -> y0), to replace the +5 x-ramp descent that intrudes into
the PI zone for leftmost-column sinks.

Candidates:
  D1: torch ladder down — column of blocks with a wall torch on one face each
      level. Each torch inverts and powers the block below it.
  D2: repeater cannot go vertical. Skip.
  D3: dust 'see-below' in a 2-wide zigzag confined to 2 columns (x, x+1) instead
      of 5 — smaller than the ramp but not 1-wide.

We need: drive a y5 dust, read y0 dust at the bottom, in a <=2-wide footprint.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

def flr(B,x0,x1,z0,z1,y=-1):
    for x in range(x0,x1+1):
        for z in range(z0,z1+1): B(x,y,z,S)

def D1(drive):
    """Torch ladder DOWN, 2-wide (x and x+1). Drive a y5 dust; each level a
    wall torch carries the (inverted) signal down one block. 5 torches y5->y0.
    2 columns: blocks at x, torches on x+1 face reading x."""
    sc=nuc.Schematic.create("d1"); B=sc.set_block_from_string
    flr(B,-2,6,-2,4)
    x,z=1,1; b=0
    # drive y5 dust at (x,b+5,z) reliably via repeater from a block riser west
    # simplest reliable: build a source tower UP first (proven), then ladder down.
    # UP tower at x0=-? too complex; drive the top block directly then torch down.
    # top: block@(x,b+5,z) powered by redstone_block on top (strong power)
    B(x,b+6,z, RB if drive else "minecraft:air")   # driver on top of tower head
    B(x,b+5,z,S)                                     # head block (strongly powered when driver=1)
    # ladder down: wall torch on the block reads it; torch OFF when block powered.
    # torch at (x+1,b+5,z) facing east reads block (x,b+5,z); powers block below?
    # A wall torch powers the block it sits against's... torch lights the block
    # ABOVE and the block it's attached to weakly. For DOWN transmission use:
    #   block@(x,y,z) powered -> torch@(x+1,y,z) OFF -> block@(x,y-1,z) unpowered
    #   -> torch@(x+1,y-1,z) ON -> ... alternating. Read bottom.
    probes=[]
    for yy in range(b+5, b, -1):
        B(x+1, yy, z, wt("east"))    # torch on east side of block col, reads block@x
        if yy-1 >= b:
            B(x, yy-1, z, S)          # block below (torch above-adjacent powers it?)
        probes.append((x+1,yy,z))
    B(x, b, z, W)  # y0 dust
    B(x, b, z-1, "minecraft:redstone_lamp")
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(30)
    seq=[1 if w.is_lit(*p) else 0 for p in probes]
    return seq, (1 if w.get_redstone_power(x,b,z)>0 else 0)

def D3(drive):
    """2-wide dust zigzag DOWN (confined to x,x+1). Mirror of the +x ramp but
    folding back so it stays in 2 columns. y5 dust -> step down alternating x."""
    sc=nuc.Schematic.create("d3"); B=sc.set_block_from_string
    flr(B,-2,6,-2,4)
    x,z=1,1; b=0
    B(x,b+6,z, RB if drive else "minecraft:air")
    B(x,b+5,z,S); B(x,b+5,z+1,W)   # hmm needs care
    # Too fiddly; focus on D1.
    return None

if __name__=="__main__":
    print("D1 torch ladder DOWN (2-wide), 5 torches y5->y0:")
    for d in (0,1):
        seq,y0 = D1(d)
        print(f"  drive={d}: torch seq(top..bottom)={seq} y0_dust={y0}")
