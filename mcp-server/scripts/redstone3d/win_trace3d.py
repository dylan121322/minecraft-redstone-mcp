"""
win_trace3d.py — signal diagnosis for the 3-D router: per-net source power vs
logical expectation on one vector, plus the source's layer so decayed vs
missing vs coupled is distinguishable.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import coupling
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
    print(f"route: shorts={shorts} nets={len(placements)}", flush=True)
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

    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))
    print(f"y={1 if P(*y_pos)>0 else 0} (want 1)  "
          f"c={1 if P(*c_pos)>0 else 0} (want 0)", flush=True)

    driver = {}
    for cname, cdata in nl["cells"].items():
        for net in cdata["outputs"].values():
            driver[net] = cname
    lvl = {}
    def net_lvl(net):
        if net in lvl:
            return lvl[net]
        if net not in driver:
            lvl[net] = 0
            return 0
        c = driver[net]
        m = 0
        for innet in nl["cells"][c]["inputs"].values():
            m = max(m, net_lvl(innet) + 1)
        lvl[net] = m
        return m

    print("\nper-net source power (vector op=3 a=1 b=0 cin=0):", flush=True)
    n_bad = 0
    for net in sorted(pl.net_sources, key=net_lvl):
        pos = pl.net_sources[net]
        pwr = P(*pos)
        act = 1 if pwr > 0 else 0
        want = exp.get(net, 0)
        mark = "  <<<" if act != want else ""
        if mark:
            n_bad += 1
        print(f"  {net:6s} lvl={net_lvl(net):2d} want={want} got={act} "
              f"(pwr={pwr}@{pos[1]}){mark}", flush=True)
    print(f"\nmismatches: {n_bad}", flush=True)


if __name__ == "__main__":
    main()
