"""MCHPRS verify via_gadget rise/drop: source pin -> rise -> trunk -> drop -> NOT pin."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleation as nuc
from via_gadget import rise_cells, drop_cells
W="minecraft:redstone_wire"; S="minecraft:stone"; RB="minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"

def build(drive, y_top):
    sc=nuc.Schematic.create("vg"); B=sc.set_block_from_string
    z=0
    for x in range(-3,60):
        for zz in range(-2,2): B(x,-1,zz,S)
    # source pin feed: redstone_block west, dust at x=0 (source)
    B(-1,0,z, RB if drive else "minecraft:air")
    B(0,0,z,W)
    # rise from (0,0) to y_top
    pr,xo=rise_cells(0,z,0,y_top)
    for (x,y,zz,b) in pr: B(x,y,zz,b)
    # trunk run on y_top from xo to xo+6 (supports below)
    for x in range(xo,xo+7):
        B(x,y_top-1,z,S); B(x,y_top,z,W)
    tx=xo+6
    # drop from (tx,y_top) to y0
    pd,xo2=drop_cells(tx,z,y_top,0)
    for (x,y,zz,b) in pd: B(x,y,zz,b)
    # feed a NOT cell at xo2+2: pin repeater[west] reads from west (xo2+1)
    B(xo2+1,0,z,W)
    B(xo2+2,0,z,rep("west"))
    B(xo2+3,0,z,S); B(xo2+4,0,z,"minecraft:redstone_wall_torch[facing=east]")
    B(xo2+5,0,z,W)   # NOT output
    return sc,(xo2+5,0,z)

for y_top in (2,4,10):
    print(f"y_top={y_top}:")
    for d in (0,1):
        sc,probe=build(d,y_top)
        w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(50)
        out=w.get_redstone_power(*probe)
        exp=0 if d else 1  # chain non-inverting, NOT inverts => out=~drive
        print(f"  drive={d}: NOT_out={out} exp={exp} {'OK' if (out>0)==(exp>0) else 'X'}")
