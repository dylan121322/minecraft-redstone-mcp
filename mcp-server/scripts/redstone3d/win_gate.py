"""
win_gate.py — gate-level diagnosis: for the mismatched nets, probe the power
at the driver gate's input feeds, internal stages and output, to decide
whether the gate itself misbehaves or its input signals never arrive.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder as PF
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=False)
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
    w.tick(80)

    def P(x, y, z):
        return w.get_redstone_power(x, y, z)

    targets = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["n11", "n31", "n32", "n18", "n20", "n22", "n23", "n25"]
    for tn in targets:
        # find driver cell
        cname = None
        for cn, c in nl["cells"].items():
            if tn in c["outputs"].values():
                cname = cn
                break
        if cname is None:
            print(f"{tn}: not driven by any cell", flush=True)
            continue
        cdata = nl["cells"][cname]
        pc = pl.placed[cname]
        ox, oy, oz = pc.origin
        print(f"\n=== {tn} <- {cname} ({cdata['type']}) origin={pc.origin} "
              f"want={ '1' if cdata['type']=='NOT' else '?' }", flush=True)
        for pin, net in cdata["inputs"].items():
            px, py, pz = pc.input_pins[pin]
            feed = (px - 1, py, pz)
            print(f"  in {pin}={net} pin={pc.input_pins[pin]} "
                  f"feed_pwr={P(*feed)} pin_pwr={P(px, py, pz)}", flush=True)
        for pin, net in cdata["outputs"].items():
            px, py, pz = pc.output_pins[pin]
            print(f"  out {pin}={net} pin={pc.output_pins[pin]} "
                  f"pwr={P(px, py, pz)}", flush=True)
        # source (published) power
        src = pl.net_sources.get(tn)
        if src:
            print(f"  source {src} pwr={P(*src)}", flush=True)
        # dump cell interior power grid (y=0, 2x depth area)
        for dz in range(pc.cell.depth):
            row = []
            for dx in range(pc.cell.width):
                p_ = P(ox + dx, oy, oz + dz)
                row.append(f"{p_:2d}" if p_ > 0 else " .")
            print(f"  y0 z{oz+dz}: " + " ".join(row), flush=True)


if __name__ == "__main__":
    main()
