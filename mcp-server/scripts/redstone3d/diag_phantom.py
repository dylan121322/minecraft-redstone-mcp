"""
diag_phantom.py — find what drives a sink when its own source is cut.

Module verification shows several sinks resting at a constant 4-8 whatever the
source does. The box geometry checks out cell by cell, and a stone shell was
measured not to conduct, so something ELSE is feeding those cells. Rather than
guess again: cut the net's source entirely, then walk its delivery path and report
where power still appears, together with every neighbouring net cell that could be
responsible.
"""
import sys, os, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_global_first import route_adaptive
from build_from_route import emit_blocks
from delivery_box import delivery_for_sink

W = "minecraft:redstone_wire"


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    net = sys.argv[2] if len(sys.argv) > 2 else "n4"
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)

    blocks = {}
    def raw(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    guarded = g.rmap.guarded_setter(raw, writer="local")
    for (_z, _n, rr, _s) in zres:
        emit_blocks(guarded, pl, rr, {n: 0 for n in nl["inputs"]})
    for p, b in g.blocks.items():
        raw(*p, b)

    base_y = pl.bounds[0][1]
    src = pl.net_sources[net]
    sinks = pl.net_sinks[net]

    # build with the net's source CUT: anything still live is foreign
    sc = nuc.Schematic.create("ph")
    for (x, y, z), s in blocks.items():
        if "wall_torch" in s and y == base_y:
            continue                      # mask floating gate torches
        sc.set_block_from_string(x, y, z, s)
    sc.set_block_from_string(src[0] - 1, base_y, src[2], "minecraft:air")
    sc.set_block_from_string(src[0], base_y, src[2], "minecraft:air")
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(90)

    print(f"[{mod}] {net}: source CUT at {src}; anything live below is foreign")
    for k in sinks:
        feed = (k[0] - 1, base_y, k[2])
        p = w.get_redstone_power(*feed)
        print(f"  sink pin ({k[0]},{k[2]}) feed{feed} = {p}")
        if p == 0:
            continue
        box, kind = delivery_for_sink((k[0], k[2]), r.trunk_y, base_y, gap=2)
        print(f"    delivery={kind} in={box.in_cell} out={box.out_cell}")
        for cell in [box.in_cell, box.out_cell]:
            print(f"      {cell} = {w.get_redstone_power(*cell)}")
        # who sits next to the feed run and is live?
        print("    live neighbours of the feed run:")
        for x in range(box.out_cell[0], k[0] + 1):
            for dz in (-1, 0, 1):
                for dy in (0, 1, -1):
                    q = (x, base_y + dy, k[2] + dz)
                    if q == (x, base_y, k[2]):
                        continue
                    if q in blocks and w.get_redstone_power(*q) > 0:
                        print(f"      {q} [{blocks[q].replace('minecraft:','')[:22]}]"
                              f" = {w.get_redstone_power(*q)}")


if __name__ == "__main__":
    main()
