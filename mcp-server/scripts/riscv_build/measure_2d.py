"""
measure_2d.py — how routable is a module on the y=0 plane alone, with HARD
short-rejection (no two different nets' dust adjacent: orthogonal, or diagonal)?
Nets that can't find a short-free y=0 path = crossings that need a bridge.
Measure failure count vs spacing to pick a strategy.
"""
import sys, os, time
from collections import deque
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
from yosys_frontend import compile_verilog
from placer import place

MODS = {"alu1": ("alu1.v", "alu1"), "Control": ("Control.v", "Control"),
        "Mux_2to1": ("Mux_2to1.v", "Mux_2to1"), "ALU_Control": ("ALU_Control.v", "ALU_Control")}

_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
# a wire at (x,z) shorts to another net's wire at any of these offsets (same y=0):
_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]


def route_2d(pl, margin=10):
    """Greedy 2D tree router on y=0. wire_owner[(x,z)]=net. Reject a step if it
    would put net's wire adjacent (8-neighborhood) to a foreign wire/pin."""
    owner = {}          # (x,z) -> net   (wires only)
    pin_owner = {}      # (x,z) -> net   (pins; a wire may sit next to its own pin)
    occ = set((p[0], p[2]) for p in pl.occupancy)  # cell bodies projected to plane
    # register pins
    for pc in pl.placed.values():
        for _p, pos in pc.input_pins.items():
            pin_owner[(pos[0], pos[2])] = None  # pin net set per-net below
        for _p, pos in pc.output_pins.items():
            pin_owner[(pos[0], pos[2])] = None
    mn, mx = pl.bounds
    bx = (mn[0]-margin, mx[0]+margin); bz = (mn[2]-margin, mx[2]+margin)

    nets = [n for n in pl.net_sinks if pl.net_sources.get(n) and pl.net_sinks.get(n)]
    # order: shortest span first
    def span(n):
        s = pl.net_sources[n]; ks = pl.net_sinks[n]
        return max(abs(s[0]-k[0])+abs(s[2]-k[2]) for k in ks)
    nets.sort(key=span)

    def foreign_adj(xz, net):
        for dx, dz in _SHELL:
            q = (xz[0]+dx, xz[1]+dz)
            o = owner.get(q)
            if o is not None and o != net:
                return True
        return False

    failed = []
    for net in nets:
        s = pl.net_sources[net]; src = (s[0], s[2])
        owner.setdefault(src, net)
        tree = {src}
        ok = True
        for k in sorted(pl.net_sinks[net], key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2])):
            goal = (k[0], k[2])
            # BFS on plane
            prev = {}; seen = set(tree); q = deque(tree); found = None
            while q:
                cur = q.popleft()
                if cur == goal:
                    found = cur; break
                for dx, dz in _H:
                    nx = (cur[0]+dx, cur[1]+dz)
                    if nx in seen:
                        continue
                    if nx != goal:
                        if not (bx[0] <= nx[0] <= bx[1] and bz[0] <= nx[1] <= bz[1]):
                            continue
                        if nx in occ:
                            continue
                        o = owner.get(nx)
                        if o is not None and o != net:
                            continue
                        if foreign_adj(nx, net):
                            continue
                    seen.add(nx); prev[nx] = cur; q.append(nx)
            if found is None:
                ok = False
                continue
            # lay path
            path = [found]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            for p in path:
                owner[p] = net
                tree.add(p)
        if not ok:
            failed.append(net)
    return failed, len(nets), len(owner)


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    vfile, top = MODS[mod]
    nl = compile_verilog(os.path.join(HERE, "..", "riscv_synth", vfile), top=top)
    print(f"{mod}: {len(nl['cells'])} gates, {len(nl.get('inputs',[]))} PI")
    for cg, rg in [(16, 10), (24, 14), (32, 20), (48, 30)]:
        pl = place(nl, col_gap=cg, row_gap=rg)
        t0 = time.time()
        failed, nnets, nwires = route_2d(pl, margin=cg)
        mn, mx = pl.bounds
        print(f"  gap({cg},{rg}) dim=({mx[0]-mn[0]}x{mx[2]-mn[2]}) nets={nnets} "
              f"wires={nwires} FAILED(need bridge)={len(failed)} {time.time()-t0:.1f}s")
