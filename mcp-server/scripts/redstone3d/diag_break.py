"""diag_break.py — for a net reported routed but whose sinks read 0, walk its
own cells in the real geometry and find WHERE the signal stops: probe every cell
the router assigned to the net (y0 dust, tower rungs, cross-plane dust, descent
staircase) and print the power, so the break point is visible."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_buildable import BuildableRouter
from build_from_route import emit_blocks

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n8"
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=4)
    print(f"{net}: failed={net in res.failed} bridges={res.bridges.get(net)}")
    blocks = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 0 for n in nls["alu1"]["inputs"]})

    src = pl.net_sources[net]; sinks = pl.net_sinks[net]
    base_y = pl.bounds[0][1]
    sc = nuc.Schematic.create("db")
    for (x, y, z), s in blocks.items():
        sc.set_block_from_string(x, y, z, s)
    sc.set_block_from_string(src[0]-1, base_y, src[2], "minecraft:air")
    sc.set_block_from_string(src[0], base_y, src[2], RB)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)

    cells = sorted(res.wires[net]) + [pos for (pos, _f) in res.repeaters[net]]
    # group by Y so the chain is readable
    byy = {}
    for p in cells:
        byy.setdefault(p[1], []).append(p)
    print(f"source={src} sinks={sinks}  net cells by Y:")
    for y in sorted(byy):
        row = byy[y]
        row.sort()
        powered = [(p, w.get_redstone_power(*p)) for p in row]
        live = [f"{p[0]},{p[2]}:{v}" for p, v in powered if v > 0]
        dead = [f"{p[0]},{p[2]}" for p, v in powered if v == 0]
        print(f"  y={y}: {len(row)} cells, live={len(live)} dead={len(dead)}")
        print(f"    live: {live[:12]}")
        print(f"    dead: {dead[:12]}")
    for k in sinks:
        print(f"  sink {k}: feed={w.get_redstone_power(k[0]-1, base_y, k[2])}")


if __name__ == "__main__":
    main()
