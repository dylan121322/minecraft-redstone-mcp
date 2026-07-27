"""
diag_route.py — diagnose PHYSICAL buildability of a route result, distinguishing:
  - vertical shorts (different-net wires 1 apart in y) -> real electrical short
  - diagonal shorts (different-net wires at dx,dy=1,dz ramp) -> real short
  - horizontal shorts (different-net wires orthogonally adjacent same y)
  - floating wires (no solid support below) -> won't build
  - stacked-same-net (own path zigzag) -> wasteful, upper floats
Compares route() vs route_negotiated() for a module.
"""
import sys, os
from collections import Counter, defaultdict
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
from yosys_frontend import compile_verilog
from placer import place
from maze_router import MazeRouter

MODS = {"Control": ("Control.v", "Control"), "alu1": ("alu1.v", "alu1"),
        "ALU_Control": ("ALU_Control.v", "ALU_Control"), "Mux_2to1": ("Mux_2to1.v", "Mux_2to1")}

def analyze(res, pl):
    owner = {}
    for net, ws in res.wires.items():
        for p in ws: owner[p] = net
    cell_solid = set(pl.occupancy)
    vshort = dshort = hshort = floating = 0
    for p, net in owner.items():
        x, y, z = p
        # support: y=0 rests on floor (ok); y>0 needs solid below (cell body or another support)
        if y > 0:
            below = (x, y-1, z)
            if below not in cell_solid and below not in owner:
                # would need a support; if below is a foreign wire -> can't support
                floating += 1
            elif below in owner and owner[below] != net:
                floating += 1  # can't put support on foreign wire
        # shorts vs different nets
        for dx, dz in [(1,0),(-1,0),(0,1),(0,-1)]:
            q = (x+dx, y, z+dz)
            if q in owner and owner[q] != net: hshort += 1
        for dy in (1,-1):
            q = (x, y+dy, z)
            if q in owner and owner[q] != net: vshort += 1
        for dx, dz in [(1,0),(-1,0),(0,1),(0,-1)]:
            for dy in (1,-1):
                q = (x+dx, y+dy, z+dz)
                if q in owner and owner[q] != net: dshort += 1
    return dict(vshort=vshort//2, dshort=dshort//2, hshort=hshort//2, floating=floating,
                wires=res.total_wires(), failed=len(res.failed))

def run(mod):
    vfile, top = MODS[mod]
    nl = compile_verilog(os.path.join(HERE, "..", "riscv_synth", vfile), top=top)
    print(f"=== {mod} ({len(nl['cells'])} gates) ===")
    pl = place(nl, col_gap=16, row_gap=10)
    r1 = MazeRouter(pl, margin=12)
    a1 = analyze(r1.route(max_iters=5), pl)
    print(f"  route(5-pass):     {a1}")
    pl2 = place(nl, col_gap=16, row_gap=10)
    r2 = MazeRouter(pl2, margin=12)
    a2 = analyze(r2.route_negotiated(max_iters=80), pl2)
    print(f"  route_negotiated:  {a2}")

if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "Control")
