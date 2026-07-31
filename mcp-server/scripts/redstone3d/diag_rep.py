"""diag_rep.py — inspect every repeater the router inserted on a net's y0 route:
its facing, the dust actually adjacent on each side, and (in the built world) the
power on its input and output sides. A repeater whose input side holds no dust,
or whose facing points at the wrong neighbour, silently cuts the net."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_buildable import BuildableRouter
from build_from_route import emit_blocks

RB = "minecraft:redstone_block"
SIDE = {"west": (-1, 0), "east": (1, 0), "north": (0, -1), "south": (0, 1)}


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n30"
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=4)
    blocks = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 0 for n in nls["alu1"]["inputs"]})
    base_y = pl.bounds[0][1]
    src = pl.net_sources[net]

    sc = nuc.Schematic.create("dr")
    for (x, y, z), s in blocks.items():
        if "wall_torch" in s:
            continue
        sc.set_block_from_string(x, y, z, s)
    sc.set_block_from_string(src[0]-1, base_y, src[2], "minecraft:air")
    sc.set_block_from_string(src[0], base_y, src[2], RB)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)

    own = {p: net for p in res.wires[net]}
    print(f"{net}: {len(res.repeaters[net])} repeaters on route "
          f"(source={src}, sinks={pl.net_sinks[net]})")
    for (pos, f) in sorted(res.repeaters[net]):
        dx, dz = SIDE[f]
        inp = (pos[0]+dx, pos[1], pos[2]+dz)      # side it reads
        outp = (pos[0]-dx, pos[1], pos[2]-dz)     # side it drives
        ib = blocks.get(inp, "-").replace("minecraft:", "")[:18]
        ob = blocks.get(outp, "-").replace("minecraft:", "")[:18]
        print(f"  rep@{pos} facing={f:5s} "
              f"IN {inp}[{ib}]={w.get_redstone_power(*inp)} "
              f"OUT {outp}[{ob}]={w.get_redstone_power(*outp)} "
              f"self={w.get_redstone_power(*pos)}")


if __name__ == "__main__":
    main()
