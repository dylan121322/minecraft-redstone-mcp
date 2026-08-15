"""
win_trace.py — signal-level diagnosis: simulate the netlist in software,
simulate the routed build in MCHPRS, and diff every net's expected vs actual
value at its source cell. The FIRST mismatching net in the dataflow is the
break. Also dumps the residual shorts with positions.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder as PF
import coupling
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def logic_sim(nl, iv):
    """Evaluate the gate netlist to fixpoint."""
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
            elif gtype == "XOR":
                out = ins[0] ^ ins[1]
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
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=False)
    print(f"route: shorts={shorts} nets={len(placements)}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    print(f"materialized: failed={res.failed}", flush=True)

    # ---- residual shorts detail ----
    occ = {}
    for n, ws in res.wires.items():
        for p in ws:
            occ[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occ[q] = n
    seen = set()
    print("residual shorts:", flush=True)
    for p, net in occ.items():
        for dx, dy, dz in coupling.shell_offsets():
            q = (p[0] + dx, p[1] + dy, p[2] + dz)
            o = occ.get(q)
            if o is None or o == net:
                continue
            key = tuple(sorted([p, q]))
            if key in seen:
                continue
            seen.add(key)
            if coupling.couples(p, q, occ):
                print(f"  {net}@{p} <-> {o}@{q}", flush=True)

    # ---- one vector: op=3 (xor) a=1 b=0 cin=0 -> y=1 c=0 ----
    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    iv = {nm(pb["a"][0]): 1, nm(pb["b"][0]): 0, nm(pb["cin"][0]): 0}
    for i in range(4):
        iv[nm(pb["op"][i])] = (3 >> i) & 1
    for inet in nl["inputs"]:
        iv.setdefault(inet, 0)
    exp = logic_sim(nl, iv)
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))

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
    print(f"\nvector op=3 a=1 b=0 cin=0 -> expect y=1 c=0", flush=True)
    print(f"MCHPRS y={1 if w.get_redstone_power(*y_pos)>0 else 0} "
          f"c={1 if w.get_redstone_power(*c_pos)>0 else 0}", flush=True)

    # ---- per-net diff: source cell power vs expected ----
    # dataflow order: inputs first, then topo levels
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
    nets_sorted = sorted(pl.net_sources, key=net_lvl)
    print("\nper-net source power vs expected:", flush=True)
    n_bad = 0
    for net in nets_sorted:
        pos = pl.net_sources[net]
        pwr = w.get_redstone_power(pos[0], pos[1], pos[2])
        act = 1 if pwr > 0 else 0
        want = exp.get(net, 0)
        mark = "" if act == want else "  <<< MISMATCH"
        if mark:
            n_bad += 1
        print(f"  {net:6s} lvl={net_lvl(net):2d} want={want} got={act} "
              f"(pwr={pwr}){mark}", flush=True)
    print(f"\ntotal mismatches: {n_bad}", flush=True)


if __name__ == "__main__":
    main()
