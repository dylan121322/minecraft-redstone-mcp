"""
test_stagger.py — MCHPRS: two nets delivering to two pins in the SAME placement
column (same px, different pz) WITHOUT their y4 vertical runs shorting.

Scheme: net k descends at a unique y4 column x_k = px - 5 - 2*k (spaced 2),
V-runs on y4 at x_k from its trunk row down to pz_k, descends staircase +x
landing at x_k+4, then a short y2 H-jog east to px-1 to feed the pin.

Wait — the descent lands at y0 (x_k+4). To reach the pin at (px,pz) we need y0
dust from x_k+4 to px-1 at row pz. Two nets' y0 jogs at different pz don't short
(different z). Verify: 2 nets, pins at (px,0) and (px,2), each fed correctly and
independently.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
S="minecraft:stone"; W="minecraft:redstone_wire"; RB="minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"
WT="minecraft:redstone_wall_torch[facing=east]"

def build(d0, d1):
    sc=nuc.Schematic.create("stag"); B=sc.set_block_from_string
    b=0
    for x in range(-2,40):
        for z in range(-2,10): B(x,b-1,z,S)
    px=30
    # two NOT cells as sinks: pin at (px,0,pz) = rep[facing=west]; body east
    for pz in (0,4):
        B(px,b,pz,rep("west")); B(px+1,b,pz,S); B(px+2,b,pz,WT); B(px+3,b,pz,W)
    # each net: a driver (redstone_block) -> climb to y4 at its own column -> V-run to pz -> descend -> y0 jog to px-1
    def net(k, pz, drive):
        # unique y4 column
        xk = px - 5 - 2*k
        row = 7 + 2*k   # trunk row (north), unique
        # driver: put a y4 dust source at (xk, b+4, row) driven by redstone_block
        B(xk, b+3, row, S); B(xk, b+4, row, RB if drive else W)
        if not drive: B(xk, b+4, row, W)
        # V-run y4 at xk from row down to pz
        lo,hi=min(row,pz),max(row,pz)
        for z in range(lo,hi+1): B(xk,b+3,z,S); B(xk,b+4,z,W)
        # descend staircase +x from (xk,pz,y4) to y0 at xk+4
        B(xk+1,b+2,pz,S); B(xk+1,b+3,pz,W)
        B(xk+2,b+1,pz,S); B(xk+2,b+2,pz,W)
        B(xk+3,b,pz,S);   B(xk+3,b+1,pz,W)
        B(xk+4,b,pz,W)
        # y0 jog east from xk+4 to px-1 at row pz
        for x in range(xk+4, px): B(x,b,pz,W)
    net(0, 0, d0)
    net(1, 4, d1)
    return sc, {"o0":(px+3,b,0), "o1":(px+3,b,4)}

ok=True
for d0 in (0,1):
    for d1 in (0,1):
        sc,pr=build(d0,d1)
        w=nuc.MchprsWorld.create_with_options(sc,True,False)
        w.tick(30)
        # NOT output = !input
        o0=1 if w.get_redstone_power(*pr["o0"])>0 else 0
        o1=1 if w.get_redstone_power(*pr["o1"])>0 else 0
        e0=1-d0; e1=1-d1
        good=(o0==e0 and o1==e1)
        ok=ok and good
        print(f"d0={d0} d1={d1} -> o0={o0}(exp{e0}) o1={o1}(exp{e1}) {'OK' if good else 'X'}")
print("STAGGER", "PASS" if ok else "FAIL")
