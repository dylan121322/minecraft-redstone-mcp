"""verify_tracks_mchprs.py — L1 for the structured TrackRouter."""
import sys, os, time
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_tracks import TrackRouter
from yosys_frontend import compile_verilog
from mchprs_sim import simulate_vectors, report

W = "minecraft:redstone_wire"; S = "minecraft:stone"; RB = "minecraft:redstone_block"

def legality(res, pl):
    owner = dict(res.wire_owner)
    SHELL = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
    shorts = 0; floats = 0
    sup = res.supports
    occ = set(pl.occupancy)
    for p, net in owner.items():
        x,y,z = p
        for dx,dz in SHELL:
            o = owner.get((x+dx,y,z+dz))
            if o and o != net: shorts += 1
        for dy in (1,-1):
            o = owner.get((x,y+dy,z))
            if o and o != net: shorts += 1
        if y > pl.bounds[0][1]:
            b = (x,y-1,z)
            if b not in sup and b not in occ and b not in owner: floats += 1
    return shorts//2, floats

def emit(schem, pl, res, inputs):
    B = schem.set_block_from_string
    mn, mx = pl.bounds
    xs = [p[0] for w in res.wires.values() for p in w] + [mn[0], mx[0]]
    zs = [p[2] for w in res.wires.values() for p in w] + [mn[2], mx[2]]
    fy = mn[1]-1
    for x in range(min(xs)-2, max(xs)+3):
        for z in range(min(zs)-2, max(zs)+3):
            B(x, fy, z, S)
    for (x,y,z) in res.supports: B(x,y,z,S)
    class A:
        def set_block_from_string(self,x,y,z,s): B(int(x),int(y),int(z),s)
    for pc in pl.placed.values(): pc.cell.emit(A(), *pc.origin)
    for net,ws in res.wires.items():
        for (x,y,z) in ws: B(x,y,z,W)
    for net,reps in res.repeaters.items():
        for (pos,f) in reps: B(pos[0],pos[1],pos[2], f"minecraft:repeater[facing={f},delay=1]")
    for net,pos in pl.primary_inputs.items():
        v = inputs.get(net,0)
        B(pos[0]-1,pos[1],pos[2], RB if v else "minecraft:air")
        B(pos[0],pos[1],pos[2], W)

def netname(bit): return f"n{bit}" if not isinstance(bit,str) else f"const_{bit}"

if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv)>1 else "alu1"
    vf = {"alu1":"alu1.v","Control":"Control.v","Mux_2to1":"Mux_2to1.v","ALU_Control":"ALU_Control.v","Imm_Gen":"Imm_Gen.v"}[mod]
    nl = compile_verilog(os.path.join(HERE,"..","riscv_synth",vf), top=mod)
    print(f"{mod}: {len(nl['cells'])} gates {dict(Counter(c['type'] for c in nl['cells'].values()))}")
    pl = place(nl, col_gap=16, row_gap=10)
    r = TrackRouter(pl)
    t0 = time.time()
    res = r.route(verbose=True)
    sh, fl = legality(res, pl)
    print(f"  wires={res.total_wires()} supports={len(res.supports)} reps={sum(len(v) for v in res.repeaters.values())} shorts={sh} floats={fl} route {time.time()-t0:.1f}s")
    if mod == "alu1":
        pb = nl["port_bits"]
        a_n,b_n,cin_n = netname(pb["a"][0]),netname(pb["b"][0]),netname(pb["cin"][0])
        op_n = [netname(x) for x in pb["op"]]
        y_n,cout_n = netname(pb["y"][0]),netname(pb["cout"][0])
        tvs=[]; specs=[]
        for op in (0,1,2,3,6):
            for a in (0,1):
                for b in (0,1):
                    for cin in (0,1):
                        iv={a_n:a,b_n:b,cin_n:cin}
                        for i in range(4): iv[op_n[i]]=(op>>i)&1
                        bb=(1-b) if op==6 else b
                        summ=a^bb^cin; cout=(a&bb)|(cin&(a^bb))
                        yv={0:a&b,1:a|b,2:summ,3:a^b,6:summ}.get(op,0)
                        tvs.append(iv); specs.append({y_n:yv,cout_n:cout})
        probes = dict(pl.primary_outputs)
        def build(schem, inputs): emit(schem, pl, res, inputs)
        test_vectors=[{"inputs":iv,"expected":sp} for iv,sp in zip(tvs,specs)]
        t1=time.time()
        results = simulate_vectors(build, list(nl["inputs"]), probes, test_vectors, ticks=30, lamp_outputs=False)
        report(mod, results)
        print(f"  sim {time.time()-t1:.1f}s")
