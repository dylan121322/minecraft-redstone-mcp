"""
test_hv_layers.py — MCHPRS: validate the 2-layer Manhattan channel architecture
primitives BEFORE writing the router.

Layers:
  y=0  cell/pin plane
  y=2  H-layer (horizontal segments only, run in X)
  y=4  V-layer (vertical segments only, run in Z)
Vias connect y0<->y2<->y4 with the verified repeater/block climb.

Questions (each a small MCHPRS experiment, PASS/FAIL):
  Q1 CLIMB y0->y2->y4: can a signal climb two layers via stacked blocks+dust?
  Q2 H over V isolation: net A horizontal dust at y=2 crossing (x,z); net B
     vertical dust at y=4 crossing the SAME (x,z) but 2 higher, with a solid
     block at y=3 between. Independent? (the whole point)
  Q3 parallel H rows at y=2 spaced 2 in Z: independent? (should match Agent B)
  Q4 parallel V cols at y=4 spaced 2 in X: independent?
"""
import sys, os
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"; A="minecraft:air"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"

def sim(build_fn, drives):
    """build_fn(B, drive_dict) places blocks; returns dict of probe positions.
    We rebuild per drive combo."""
    results=[]
    for dv in drives:
        sc=nuc.Schematic.create("hv")
        probes={}
        def B(x,y,z,s): sc.set_block_from_string(x,y,z,s)
        probes=build_fn(B, dv)
        w=nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(24)
        out={k:(1 if w.get_redstone_power(*p)>0 else 0) for k,p in probes.items()}
        results.append((dv,out))
    return results

def floor(B, x0,x1,z0,z1,y=-1):
    for x in range(x0,x1+1):
        for z in range(z0,z1+1): B(x,y,z,S)

# ---- Q1: climb y0 -> y2 -> y4 ----
def q1(B, dv):
    floor(B,-1,12,-1,3)
    d=dv["d"]
    z=1
    # source dust at x=0 driven
    B(0,0,z, RB if d else W)
    if not d: B(0,0,z,W)
    B(1,0,z, rep("west"))
    # climb to y2 (Agent A): block@2 y0 + dust y1; block@3 y1 + dust y2
    B(2,0,z,S); B(2,1,z,W)
    B(3,1,z,S); B(3,2,z,W)
    # continue climb y2->y4: block@4 y2 + dust y3; block@5 y3 + dust y4
    B(4,2,z,S); B(4,3,z,W)
    B(5,3,z,S); B(5,4,z,W)
    # short y4 run + lamp
    B(6,3,z,S); B(6,4,z,W)
    B(7,3,z,S); B(7,4,z,"minecraft:redstone_lamp")
    return {"lamp":(7,4,z)}

# ---- Q2: H(y2) of net A crossing V(y4) of net B at same (x,z) ----
def q2(B, dv):
    floor(B,-1,14,-1,10)
    da,db=dv["a"],dv["b"]
    cx,cz=7,5   # crossing point
    # Net A: horizontal dust at y=2 along x, at z=cz. supports at y1.
    for x in range(2,13):
        B(x,1,cz,S); B(x,2,cz,W)
    # drive A from west via a climb at x=2? simpler: put redstone_block feeding
    # the y2 dust through a block riser at x=1
    B(1,1,cz,S); B(1,2,cz, RB if da else A)
    # lamp A at east: riser down not needed, read the y2 dust end
    # Net B: vertical dust at y=4 along z, at x=cx. supports at y3. Crosses A at (cx,cz).
    for z in range(2,9):
        B(cx,3,z,S); B(cx,4,z,W)
    B(cx,3,1,S); B(cx,4,1, RB if db else A)  # drive B from z=1 side
    # at crossing (cx,cz): A has dust y2 + support y1; B has dust y4 + support y3.
    # y3 support block sits between A(y2) and B(y4). Read both far ends.
    return {"A":(12,2,cz), "B":(cx,4,8)}

# ---- Q3: parallel H rows y2 spaced 2 ----
def q3(B, dv):
    floor(B,-1,14,-1,6)
    da,db=dv["a"],dv["b"]
    for x in range(2,13):
        B(x,1,1,S); B(x,2,1,W)   # row A z=1
        B(x,1,3,S); B(x,2,3,W)   # row B z=3 (sep 2)
    B(1,1,1,S); B(1,2,1, RB if da else A)
    B(1,1,3,S); B(1,2,3, RB if db else A)
    return {"A":(12,2,1),"B":(12,2,3)}

def run(name, fn, drives):
    res=sim(fn, drives)
    ok=True
    for dv,out in res:
        exp={k:dv.get(k[-1] if len(k)==1 else k, None) for k in out}
        print(f"  {name} {dv} -> {out}")
    return res

if __name__=="__main__":
    print("Q1 climb y0->y2->y4:")
    for dv,out in sim(q1,[{"d":0},{"d":1}]):
        print(f"   drive={dv['d']} lamp={out['lamp']} {'OK' if out['lamp']==dv['d'] else 'X'}")
    print("Q2 H(y2)A x V(y4)B isolation:")
    ok=True
    for dv,out in sim(q2,[{"a":0,"b":0},{"a":1,"b":0},{"a":0,"b":1},{"a":1,"b":1}]):
        good = out["A"]==dv["a"] and out["B"]==dv["b"]
        ok = ok and good
        print(f"   a={dv['a']} b={dv['b']} -> A={out['A']} B={out['B']} {'OK' if good else 'X'}")
    print(f"   Q2 {'PASS' if ok else 'FAIL'}")
    print("Q3 parallel H rows sep2:")
    ok=True
    for dv,out in sim(q3,[{"a":1,"b":0},{"a":0,"b":1}]):
        good = out["A"]==dv["a"] and out["B"]==dv["b"]
        ok=ok and good
        print(f"   a={dv['a']} b={dv['b']} -> A={out['A']} B={out['B']} {'OK' if good else 'X'}")
    print(f"   Q3 {'PASS' if ok else 'FAIL'}")
