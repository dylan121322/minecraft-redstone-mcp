"""
win_gate3d.py — gate-level power diagnosis for the 3-D router: probe the
driver gate's input feeds, internal power grid and output for the mismatched
nets, to see exactly where the gate breaks.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 12.0
    PF.DROP_COST = 10.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0,
                         fanout_mult=12.0)
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    iv = {nm(pb["a"][0]): 1, nm(pb["b"][0]): 0, nm(pb["cin"][0]): 0}
    for i in range(4):
        iv[nm(pb["op"][i])] = (3 >> i) & 1
    for inet in nl["inputs"]:
        iv.setdefault(inet, 0)

    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, iv)
    sc = nuc.Schematic.create("t")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(120)

    def P(x, y, z):
        return w.get_redstone_power(x, y, z)

    targets = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["n11", "n28", "n30", "n27"]
    for tn in targets:
        cname = None
        for cn, c in nl["cells"].items():
            if tn in c["outputs"].values():
                cname = cn
                break
        if cname is None:
            print(f"{tn}: no driver", flush=True)
            continue
        cdata = nl["cells"][cname]
        pc = pl.placed[cname]
        ox, oy, oz = pc.origin
        print(f"\n=== {tn} <- {cname} ({cdata['type']}) origin={pc.origin}",
              flush=True)
        for pin, net in cdata["inputs"].items():
            px, py, pz = pc.input_pins[pin]
            feed = (px - 1, py, pz)
            print(f"  in {pin}={net} feed_pwr={P(*feed)}", flush=True)
        for pin, net in cdata["outputs"].items():
            px, py, pz = pc.output_pins[pin]
            print(f"  out {pin}={net} pin_pwr={P(px, py, pz)}", flush=True)
        src = pl.net_sources.get(tn)
        if src:
            print(f"  source {src} pwr={P(*src)}", flush=True)
        for dz in range(pc.cell.depth):
            row = []
            for dx in range(pc.cell.width):
                p_ = P(ox + dx, oy, oz + dz)
                row.append(f"{p_:2d}" if p_ > 0 else " .")
            print(f"  y0 z{oz+dz}: " + " ".join(row), flush=True)
        # y1 row (torch tips / upper structure)
        for dz in range(pc.cell.depth):
            row = []
            for dx in range(pc.cell.width):
                p_ = P(ox + dx, oy + 1, oz + dz)
                row.append(f"{p_:2d}" if p_ > 0 else " .")
            print(f"  y1 z{oz+dz}: " + " ".join(row), flush=True)


if __name__ == "__main__":
    main()
