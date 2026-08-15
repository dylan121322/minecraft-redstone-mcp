"""
win_allgates.py — probe ALL 24 gates at once: input feed powers, output pin
power vs the logical expectation, gate type and origin. One run locates every
electrically-wrong gate so the interference pattern is visible in one shot.
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


def logic_sim(nl, iv):
    vals = {n: int(v) for n, v in iv.items()}
    changed = True
    for _ in range(50):
        if not changed:
            break
        changed = False
        for cname, cdata in nl["cells"].items():
            gtype = cdata["type"]
            ins = [vals.get(net, 0) for net in cdata["inputs"].values()]
            if gtype == "NOT":
                out = 1 - ins[0]
            elif gtype == "AND":
                out = 1 if all(ins) else 0
            elif gtype == "OR":
                out = 1 if any(ins) else 0
            elif gtype == "NAND":
                out = 0 if all(ins) else 1
            elif gtype == "NOR":
                out = 1 if not any(ins) else 0
            else:
                raise ValueError(gtype)
            for net in cdata["outputs"].values():
                if vals.get(net, -1) != out:
                    changed = True
                vals[net] = out
    return vals


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
    exp = logic_sim(nl, iv)

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

    print(f"\n{'gate':10s} {'type':5s} {'origin':>14s} {'in feeds':>24s} "
          f"{'out_pwr':>8s} {'want':>5s} {'got':>4s}", flush=True)
    n_bad = 0
    for cname in sorted(nl["cells"]):
        cdata = nl["cells"][cname]
        pc = pl.placed[cname]
        ox, oy, oz = pc.origin
        feeds = []
        for pin, net in cdata["inputs"].items():
            px, py, pz = pc.input_pins[pin]
            feeds.append(f"{net}={P(px - 1, py, pz)}")
        outs = list(cdata["outputs"].values())
        onet = outs[0]
        px, py, pz = pc.output_pins["Q"]
        opwr = P(px, py, pz)
        want = exp.get(onet, 0)
        got = 1 if opwr > 0 else 0
        mark = "  <<<" if got != want else ""
        if mark:
            n_bad += 1
        print(f"{cname:10s} {cdata['type']:5s} ({ox:3d},{oz:3d}) "
              f"{' '.join(f'{f:>7s}' for f in feeds):>24s} "
              f"{opwr:8d} {want:5d} {got:4d}{mark}", flush=True)
    print(f"\ngates wrong: {n_bad}/24", flush=True)


if __name__ == "__main__":
    main()
