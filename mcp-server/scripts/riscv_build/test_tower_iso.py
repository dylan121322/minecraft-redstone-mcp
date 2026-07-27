"""
test_tower_iso.py — MCHPRS: how close can two different nets' vertical torch
towers stand without coupling? Determines router packing density.

Two towers A and B at columns separated by `sep` in x (same z). Drive each
independently through all 4 combos; read each top torch. PASS iff independent.
Try sep = 1, 2, 3.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"

def flr(B,x0,x1,z0,z1,y=-1):
    for x in range(x0,x1+1):
        for z in range(z0,z1+1): B(x,y,z,S)

def tower(B, x, z, drive, torches=3):
    b=0
    B(x-3,b,z, RB if drive else "minecraft:air")
    B(x-2,b,z,W)
    B(x-1,b,z,"minecraft:repeater[facing=west,delay=1]")
    B(x,b,z,S)
    y=b; tops=[]
    for i in range(torches):
        B(x,y+1,z,"minecraft:redstone_torch")
        B(x,y+2,z,S)
        tops.append((x,y+1,z))
        y+=2
    return tops[-1]

def tower_north(B, x, z, drive, torches=3):
    """Same tower but driven from the NORTH (z-3..z-1) so its drive chain runs in
    z, not x — avoids overlapping tower A's body when towers are close in x."""
    b=0
    B(x,b,z-3, RB if drive else "minecraft:air")
    B(x,b,z-2,W)
    B(x,b,z-1,"minecraft:repeater[facing=north,delay=1]")
    B(x,b,z,S)
    y=b; tops=[]
    for i in range(torches):
        B(x,y+1,z,"minecraft:redstone_torch")
        B(x,y+2,z,S)
        tops.append((x,y+1,z))
        y+=2
    return tops[-1]

def run(sep):
    ok=True
    for da in (0,1):
        for db in (0,1):
            sc=nuc.Schematic.create("iso"); B=sc.set_block_from_string
            flr(B,-10,40,-6,8)
            # tower A driven from west (its chain at x=2..4, tower at x=5)
            ta=tower(B, 5, 1, da)
            # tower B far enough east that its west-drive chain doesn't touch A;
            # separate the TOWERS by sep in x but drive B from a different z lane
            # so its chain never overlaps A's tower. Put B tower at x=5+sep, drive
            # chain from the NORTH (z) instead of west to avoid x-overlap.
            tb=tower_north(B, 5+sep, 1, db)
            w=nuc.MchprsWorld.create_with_options(sc,True,False); w.tick(24)
            la=1 if w.is_lit(*ta) else 0
            lb=1 if w.is_lit(*tb) else 0
            # top after 3 torches = NOT(drive)
            ea,eb=1-da,1-db
            good=(la==ea and lb==eb)
            ok=ok and good
            if not good:
                print(f"    sep={sep} da={da} db={db}: topA={la}(exp{ea}) topB={lb}(exp{eb}) X")
    return ok

if __name__=="__main__":
    for sep in (1,2,3):
        print(f"sep={sep}: {'PASS - isolated' if run(sep) else 'FAIL - coupled'}")
