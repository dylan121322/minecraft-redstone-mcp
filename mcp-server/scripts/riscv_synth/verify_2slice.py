"""Verify 2-slice composite with carry chain in MCHPRS. Small enough to sim fast.
Test: ADD 1+1 → bit0: y=0 cout=1; bit1: y=1 cout=0 (carry propagates)."""
import sys, os, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import nucleation as n
from placer import place
from maze_router import MazeRouter

nl = json.load(open(os.path.join(HERE, "nl_alu1.json")))
pl = place(nl, col_gap=10, row_gap=6)
res = MazeRouter(pl, margin=10).route_negotiated(max_iters=300)
pb = nl["port_bits"]; pi = pl.primary_inputs; po = pl.primary_outputs
def pin(port, i=0): b = pb[port][i]; return pi[f"n{b}"]
def pout(port, i=0): b = pb[port][i]; return po[f"n{b}"]
cin_p=pin("cin"); cout_p=pout("cout"); a_p=pin("a"); b_p=pin("b")
op_ps=[pin("op",i) for i in range(4)]; y_p=pout("y")
mn,mx=pl.bounds; sw=mx[0]-mn[0]+1; pitch=sw+8; zbus0=mx[2]+2
NSLICES=2

def wire(s,x,y,z):
    if y>0: s.set_block_from_string(x,y-1,z,"minecraft:stone")
    s.set_block_from_string(x,y,z,"minecraft:redstone_wire")

def drive(s,pos,val):
    s.set_block_from_string(pos[0]-1,pos[1],pos[2],"minecraft:redstone_block" if val else "minecraft:air")

def compose_2slice(op, a0,b0,a1,b1, cin0):
    s=n.Schematic.create("a2")
    total_w=pitch*NSLICES+20
    s.fill_cuboid(mn[0]-3,-1,mn[2]-3,mn[0]+total_w,-1,zbus0+12,"minecraft:stone")
    for i in range(NSLICES):
        dx=i*pitch
        for pc in pl.placed.values():
            pc.cell.emit(s,pc.origin[0]+dx,pc.origin[1],pc.origin[2])
        for net,ws in res.wires.items():
            for (x,y,z) in ws: wire(s,x+dx,y,z)
        for net,rr in res.repeaters.items():
            for(pos,f) in rr:
                if y_p[1]>0: s.set_block_from_string(pos[0]+dx,pos[1]-1,pos[2],"minecraft:stone")
                s.set_block_from_string(pos[0]+dx,pos[1],pos[2],f"minecraft:repeater[facing={f},delay=1]")
    # carry chain: slice[0].cout -> slice[1].cin
    cx0=(cout_p[0],0,cout_p[2]); cx1=(cin_p[0]+pitch,0,cin_p[2])
    lane_x=mx[0]+2; z=cx0[2]
    for x in range(cx0[0]+1,lane_x+1): wire(s,x,0,z)
    z0,z1=sorted([cx0[2],cx1[2]])
    for zz in range(z0,z1+1): wire(s,lane_x,0,zz)
    for x in range(lane_x,cx1[0]): wire(s,x,0,cx1[2])
    # op bus (2-slice wide)
    for k in range(4):
        bz=zbus0+k*2
        for x in range(mn[0],mn[0]+pitch*NSLICES): wire(s,x,0,bz)
        for i in range(NSLICES):
            px=op_ps[k][0]+i*pitch
            for zz in range(min(op_ps[k][2],bz),max(op_ps[k][2],bz)+1): wire(s,px,0,zz)
    # drive inputs
    drive(s,(a_p[0],0,a_p[2]),a0); drive(s,(b_p[0],0,b_p[2]),b0)
    drive(s,(a_p[0]+pitch,0,a_p[2]),a1); drive(s,(b_p[0]+pitch,0,b_p[2]),b1)
    drive(s,(cin_p[0],0,cin_p[2]),cin0)  # bit0 cin
    for k in range(4): drive(s,(mn[0]-1,0,zbus0+k*2),(op>>k)&1)
    return s, [(y_p[0]+i*pitch,0,y_p[2]) for i in range(NSLICES)]

print("=== 2-slice carry-chain MCHPRS test ===")
# Test 1: ADD 1+1 → bit0(1+1=0 carry1), bit1(0+0+carry1=1) → y[1:0]=10=2
# Test 2: ADD 0+0 → y=0, cout=0
# Test 3: SUB 3-1 (data1=3=11b, data2=1=01b) → bit0:1-1=0 cout=0, bit1:1-0=0 → y=0
tests=[(2,(1,1,0,0,0),(0,0,2)),(2,(0,0,0,0,0),(0,0,0)),(6,(1,1,0,1,1),(0,0,2))]
ok=0
for op,(a0,b0,a1,b1,cin0),(exp0,exp1,_) in tests:
    t=time.time()
    s,yabs=compose_2slice(op,a0,b0,a1,b1,cin0)
    print(f"  built {s.block_count()}b in {time.time()-t:.1f}s",flush=True)
    t=time.time()
    w=n.MchprsWorld.create_with_options(s,True,False)
    print(f"  MCHPRS create {time.time()-t:.1f}s",flush=True)
    w.tick(80)
    g0=1 if w.get_redstone_power(*yabs[0])>0 else 0
    g1=1 if w.get_redstone_power(*yabs[1])>0 else 0
    m=(g0==exp0 and g1==exp1); ok+=m
    print(f"  op={op} a={a0}{a1} b={b0}{b1} cin0={cin0} -> y={g1}{g0} exp y={exp1}{exp0} {'OK' if m else 'X'}",flush=True)
print(f"\n2-slice: {ok}/{len(tests)} {'CARRY CHAIN WORKS' if ok==len(tests) else 'FAIL'}")
