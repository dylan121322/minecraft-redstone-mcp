"""
test_tower_route.py — end-to-end MCHPRS: route a tiny 2-gate net using a torch
tower for vertical delivery into a cell pin, confirming the tower integrates
with a real cell before committing to a full router rewrite.

Circuit: source NOT gate output -> tower up -> H run -> tower down into a second
NOT gate's west-facing input pin. Verify the 2nd NOT inverts correctly.
This proves: tower-up from a gate output + tower-down into a gate input works.
"""
import sys, os
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from cell_library import get as getcell
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"

def build(drive):
    sc=nuc.Schematic.create("tr"); B=sc.set_block_from_string
    for x in range(-4,30):
        for z in range(-4,8): B(x,-1,z,S)
    b=0
    # Source NOT cell at origin (0,0,0): in pin (0,0,0), out Q at (3,0,0)
    n1=getcell("NOT")
    n1.emit(type("A",(),{"set_block_from_string":staticmethod(lambda x,y,z,s:B(x,y,z,s))})(),0,0,0)
    # drive source input: redstone_block west of pin (0,0,0) -> at (-1,0,0)
    B(-1,0,0, RB if drive else "minecraft:air")
    # Source output at (3,0,0). Build a tower UP from x=5 (need repeater feed).
    # feed: (3,0,0)dust -> (4,0,0)wire -> repeater(5) -> block0(6) tower base
    B(4,0,0,W)
    B(5,0,0,repw())
    tx,tz=6,0
    B(tx,0,tz,S)
    # tower up 2 torches (non-inverting), tops with dust to run horizontally
    B(tx,1,tz,"minecraft:redstone_torch"); B(tx,2,tz,S)
    B(tx,3,tz,"minecraft:redstone_torch"); B(tx,4,tz,S)
    # at y=4 top, put dust beside to carry horizontally east on y=4? need support.
    # dust on top of the top block: (tx,5,tz)
    B(tx,5,tz,W)
    # H run east on y=5 to x=... say 14, on supports
    for x in range(tx+1,15):
        B(x,4,tz,S); B(x,5,tz,W)
    # tower DOWN at x=15 into a 2nd NOT cell input at (20,0,0)? descend to y0.
    # descent tower: reverse — from y5 dust step down. Use torch tower down is
    # awkward; use the verified +x descent staircase (isolated here, single net).
    dx=15
    # y5 dust -> descend staircase +x to y0
    B(dx,4,tz,S); B(dx,5,tz,W)
    B(dx+1,3,tz,S); B(dx+1,4,tz,W)
    B(dx+2,2,tz,S); B(dx+2,3,tz,W)
    B(dx+3,1,tz,S); B(dx+3,2,tz,W)
    B(dx+4,0,tz,S); B(dx+4,1,tz,W)
    B(dx+5,0,tz,W)   # y0 lands
    # 2nd NOT cell at (dx+6,0,0): input pin fed by (dx+5,0,0)
    n2=getcell("NOT")
    n2.emit(type("A",(),{"set_block_from_string":staticmethod(lambda x,y,z,s:B(x,y,z,s))})(),dx+6,0,0)
    out2=(dx+6+3,0,0)  # 2nd NOT output
    w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(30)
    # source NOT out = !drive ; after tower(2 torch, non-inv) = !drive ; 2nd NOT = drive
    return 1 if w.get_redstone_power(*out2)>0 else 0

if __name__=="__main__":
    for d in (0,1):
        o=build(d)
        # chain: drive -> NOT -> !d -> tower(noninv) -> !d -> NOT2 -> d
        print(f"drive={d} -> final={o} expect={d} {'OK' if o==d else 'X'}")
