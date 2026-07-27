"""
try_planar.py — can a module route on a SINGLE plane (y=0)? A planar route is
trivially buildable: every wire rests on the floor slab, no supports, no
vertical shorts. Trade wider placement for buildability.

Tries increasing spacing until route_negotiated legalizes at y_max=0.
"""
import sys, os, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
from yosys_frontend import compile_verilog
from placer import place
from maze_router import MazeRouter

MODS = {
    "Control": ("Control.v", "Control"),
    "ALU_Control": ("ALU_Control.v", "ALU_Control"),
    "Mux_2to1": ("Mux_2to1.v", "Mux_2to1"),
    "Imm_Gen": ("Imm_Gen.v", "Imm_Gen"),
    "alu1": ("alu1.v", "alu1"),
}

def try_module(module, spacings):
    vfile, top = MODS[module]
    nl = compile_verilog(os.path.join(HERE, "..", "riscv_synth", vfile), top=top)
    ng = len(nl["cells"])
    for (cg, rg) in spacings:
        pl = place(nl, col_gap=cg, row_gap=rg)
        r = MazeRouter(pl, y_min=0, y_max=0, margin=cg)  # PLANAR ONLY
        t0 = time.time()
        res = r.route_negotiated(max_iters=120, verbose=False)
        dt = time.time() - t0
        # check legality: no shared voxel, no failed net
        from collections import Counter
        allpos = Counter()
        for net, ws in res.wires.items():
            for p in ws: allpos[p] += 1
        shared = sum(1 for c in allpos.values() if c > 1)
        mn, mx = pl.bounds
        dim = (mx[0]-mn[0], mx[2]-mn[2])
        print(f"  {module} gates={ng} gap=({cg},{rg}) dim={dim} "
              f"wires={res.total_wires()} shared={shared} failed={len(res.failed)} {dt:.1f}s "
              f"{'LEGAL-PLANAR' if shared==0 and not res.failed else 'no'}", flush=True)
        if shared == 0 and not res.failed:
            return True
    return False

if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "Control"
    spacings = [(16, 10), (24, 16), (32, 22), (48, 32)]
    ok = try_module(mod, spacings)
    print(f"{mod}: {'PLANAR ROUTABLE' if ok else 'needs 3D (planar failed at all spacings)'}")
