"""Windows compute job: negotiated-congestion route a RISC-V module and export.
Run on the RTX 5080 box for the heavy PathFinder iterations.

Usage: py route_job.py <module_name> <verilog_file> <top> [max_iters]
Outputs E:\\rs3d\\riscv\\<module>.litematic + <module>_route.json
"""
import sys, os, time, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))       # E:\rs3d
sys.path.insert(0, HERE)
import nucleation as n
from placer import place
from maze_router import MazeRouter
from collections import Counter

def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Control"
    nl_json = sys.argv[2] if len(sys.argv) > 2 else f"nl_{name}.json"
    max_iters = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    # Load pre-synthesized netlist (yosys runs on the Mac; Win only routes)
    nl = json.load(open(os.path.join(HERE, nl_json)))
    print(f"[{name}] {len(nl['cells'])} gates", flush=True)

    pl = place(nl, col_gap=8, row_gap=4)
    r = MazeRouter(pl, margin=8)
    t = time.time()
    # big modules: parallel router (all cores); small: serial (avoids mp overhead)
    if len(nl["cells"]) >= 40:
        res = r.route_negotiated_parallel(max_iters=max_iters, verbose=True)
    else:
        res = r.route_negotiated(max_iters=max_iters, verbose=True)
    dt = time.time() - t

    # legality check
    own = Counter()
    for net, ws in res.wires.items():
        for p in ws:
            own[p] += 1
    shared = [p for p, c in own.items() if c > 1]
    print(f"[{name}] route {dt:.1f}s wires={res.total_wires()} "
          f"shared={len(shared)} unrouted={len(res.failed)}", flush=True)

    # export litematic (only if legal)
    if not shared and not res.failed:
        mn, mx = pl.bounds
        s = n.Schematic.create(name)
        s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mx[0]+3, -1, mx[2]+3, "minecraft:stone")
        for pc in pl.placed.values():
            pc.cell.emit(s, *pc.origin)
        for net, ws in res.wires.items():
            for (x, y, z) in ws:
                if y > 0:
                    s.set_block_from_string(x, y-1, z, "minecraft:stone")
                s.set_block_from_string(x, y, z, "minecraft:redstone_wire")
        for net, reps in res.repeaters.items():
            for (pos, f) in reps:
                s.set_block_from_string(pos[0], pos[1], pos[2],
                                        f"minecraft:repeater[facing={f},delay=1]")
        for net, pos in pl.primary_inputs.items():
            s.set_block_from_string(pos[0], pos[1], pos[2], "minecraft:redstone_wire")
        outp = os.path.join(HERE, f"{name}.litematic")
        s.save_to_file(outp)
        print(f"[{name}] LEGAL — litematic saved {os.path.getsize(outp)}B "
              f"{s.block_count()} blocks", flush=True)
        status = "LEGAL"
    else:
        status = "ILLEGAL"
        print(f"[{name}] NOT fully legalized (shared={len(shared)})", flush=True)

    json.dump({"module": name, "gates": len(nl["cells"]),
               "wires": res.total_wires(), "shared": len(shared),
               "unrouted": res.failed, "time_s": round(dt, 1),
               "status": status},
              open(os.path.join(HERE, f"{name}_route.json"), "w"))

if __name__ == "__main__":
    main()
