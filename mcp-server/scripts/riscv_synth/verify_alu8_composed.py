"""Verify the composed bit-sliced 8-bit ALU in MCHPRS (physical redstone sim).

Rebuilds the composed schematic, injects data1/data2/op via redstone_block at
each slice's west-edge input pins, ticks MCHPRS, reads ALU_result from the y
output pins across all 8 slices. Confirms the carry chain + op bus actually
carry signal in real redstone."""
import sys, os, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import nucleation as n
from placer import place
from maze_router import MazeRouter


def build_slice():
    nl = json.load(open(os.path.join(HERE, "nl_alu1.json")))
    pl = place(nl, col_gap=10, row_gap=6)
    res = MazeRouter(pl, margin=10).route_negotiated(max_iters=300)
    return nl, pl, res


def compose(pl, res, nl, inputs):
    """Build composed 8-bit ALU with given inputs {data1,data2,op} driven.
    Returns (schematic, y_pin_abs_list, out_read_dir)."""
    mn, mx = pl.bounds
    sw = mx[0]-mn[0]+1; pitch = sw + 8
    pi = pl.primary_inputs; po = pl.primary_outputs; pb = nl["port_bits"]
    def pin(port, i=0):
        b = pb[port][i]; return pi[f"n{b}"]
    def pout(port, i=0):
        b = pb[port][i]; return po[f"n{b}"]
    cin_p = pin("cin"); cout_p = pout("cout")
    a_p = pin("a"); b_p = pin("b"); op_ps = [pin("op", i) for i in range(4)]
    y_p = pout("y")

    s = n.Schematic.create("alu8v")
    total_w = pitch*8 + 20
    zbus0 = mx[2] + 2
    s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mn[0]+total_w, -1, zbus0+12, "minecraft:stone")

    def wire(x,y,z):
        if y>0: s.set_block_from_string(x,y-1,z,"minecraft:stone")
        s.set_block_from_string(x,y,z,"minecraft:redstone_wire")
    def rep(x,y,z,f):
        if y>0: s.set_block_from_string(x,y-1,z,"minecraft:stone")
        s.set_block_from_string(x,y,z,f"minecraft:repeater[facing={f},delay=1]")

    for i in range(8):
        dx = i*pitch
        for pc in pl.placed.values():
            pc.cell.emit(s, pc.origin[0]+dx, pc.origin[1], pc.origin[2])
        for net,ws in res.wires.items():
            for (x,y,z) in ws: wire(x+dx,y,z)
        for net,reps in res.repeaters.items():
            for (pos,f) in reps: rep(pos[0]+dx,pos[1],pos[2],f)

    # carry chain
    for i in range(7):
        cout_abs=(cout_p[0]+i*pitch,0,cout_p[2]); cin_abs=(cin_p[0]+(i+1)*pitch,0,cin_p[2])
        lane_x=mn[0]+i*pitch+sw+2; z=cout_abs[2]; run=0
        for x in range(cout_abs[0]+1,lane_x+1):
            wire(x,0,z); run+=1
            if run%15==0: rep(x,0,z,"west")
        z0,z1=sorted([cout_abs[2],cin_abs[2]])
        for zz in range(z0,z1+1): wire(lane_x,0,zz)
        run=0
        for x in range(lane_x,cin_abs[0]):
            wire(x,0,cin_abs[2]); run+=1
            if run%15==0: rep(x,0,cin_abs[2],"west")
    # op bus
    for k in range(4):
        bus_z=zbus0+k*2; run=0
        for x in range(mn[0],mn[0]+pitch*8):
            wire(x,0,bus_z); run+=1
            if run%15==0: rep(x,0,bus_z,"west")
        for i in range(8):
            px=op_ps[k][0]+i*pitch; z0,z1=sorted([op_ps[k][2],bus_z])
            for zz in range(z0,z1+1): wire(px,0,zz)

    # ---- drive inputs ----
    d1,d2,op = inputs["data1"], inputs["data2"], inputs["op"]
    def drive(pos, val):
        # place redstone_block one block WEST of the input pin
        s.set_block_from_string(pos[0]-1, pos[1], pos[2],
                                "minecraft:redstone_block" if val else "minecraft:air")
    for i in range(8):
        drive((a_p[0]+i*pitch, 0, a_p[2]), (d1>>i)&1)
        drive((b_p[0]+i*pitch, 0, b_p[2]), (d2>>i)&1)
    # op driven onto the bus (west end of each bus lane)
    for k in range(4):
        bz = zbus0+k*2
        s.set_block_from_string(mn[0]-1, 0, bz,
                                "minecraft:redstone_block" if (op>>k)&1 else "minecraft:air")
    # bit0 cin = is_sub
    drive((cin_p[0], 0, cin_p[2]), 1 if op==6 else 0)

    y_abs = [(y_p[0]+i*pitch, 0, y_p[2]) for i in range(8)]
    return s, y_abs


def main():
    print("[verify] building slice...", flush=True)
    nl, pl, res = build_slice()
    def ref(d1,d2,op): return {0:d1&d2,1:d1|d2,2:(d1+d2)&0xFF,3:d1^d2,6:(d1-d2)&0xFF}.get(op,0)

    tests = [
        (5,3,2),(200,100,2),(255,1,2),   # ADD (incl carry)
        (10,3,6),(5,8,6),                 # SUB (incl borrow)
        (0xF0,0x0F,0),(0xAA,0x55,1),(0xFF,0x0F,3),  # AND/OR/XOR
    ]
    opname={0:"AND",1:"OR",2:"ADD",3:"XOR",6:"SUB"}
    print("[verify] MCHPRS simulation of composed 8-bit ALU:", flush=True)
    ok=0
    for d1,d2,op in tests:
        s, y_abs = compose(pl, res, nl, {"data1":d1,"data2":d2,"op":op})
        w = n.MchprsWorld.create_with_options(s, True, False)
        w.tick(120)
        got=0
        for i,(x,y,z) in enumerate(y_abs):
            if w.get_redstone_power(x,y,z) > 0: got |= (1<<i)
        exp = ref(d1,d2,op)
        m = got==exp; ok+=m
        print(f"  {opname[op]:4} {d1:3},{d2:3} -> {got:3} (exp {exp:3}) {'OK' if m else 'X'}", flush=True)
    print(f"[verify] {ok}/{len(tests)} — composed ALU {'WORKS in redstone' if ok==len(tests) else 'has wiring issues'}", flush=True)


if __name__ == "__main__":
    main()
