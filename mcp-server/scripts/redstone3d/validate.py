"""
validate.py — end-to-end validation of saved placements:
    materialize -> emit -> MCHPRS, then compare refresh3d's power model
    against the REAL per-feed powers for a chosen vector, plus the 40-vector
    truth table. The definitive check that the router's fed-check and the
    materialized world agree.

usage: python validate.py [placements.json] [op,a,b,cin]...
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "riscv_synth"))
import refresh3d
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "riscv_synth", "netlists.json")


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
    fname = sys.argv[1] if len(sys.argv) > 1 else "last_placements.json"
    dump = json.load(open(fname))
    placements = dump["placements"]
    nls = json.load(open(NETLISTS))
    nl = nls[dump.get("mod", "alu1")]
    pl = place(nl, col_gap=dump.get("col_gap", 16), row_gap=16)

    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    print(f"materialized: failed={len(res.failed)} {res.failed[:6]} "
          f"wires={res.total_wires()} reps="
          f"{sum(len(v) for v in res.repeaters.values())}", flush=True)

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))

    # ---- 40-vector truth table (sequential) ----
    def one(iv, ticks=80):
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
        w.tick(ticks)
        return (1 if w.get_redstone_power(*y_pos) > 0 else 0,
                1 if w.get_redstone_power(*c_pos) > 0 else 0)

    ny = nc = both = 0
    yv_set = set(); cv_set = set()
    per_op = {}
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    iv = {a_n: a, b_n: bv, cin_n: cin}
                    for i in range(4):
                        iv[op_n[i]] = (op >> i) & 1
                    for inet in nl["inputs"]:
                        iv.setdefault(inet, 0)
                    yv, cv = one(iv)
                    bb = (1 - bv) if op == 6 else bv
                    summ = a ^ bb ^ cin
                    cout = (a & bb) | (cin & (a ^ bb))
                    ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv,
                          6: summ}.get(op, 0)
                    ny += (yv == ey); nc += (cv == cout)
                    both += (yv == ey and cv == cout)
                    yv_set.add(yv); cv_set.add(cv)
                    per_op[op] = per_op.get(op, 0) + (yv == ey and cv == cout)
    print(f"MCHPRS 40: y_ok={ny}/40 c_ok={nc}/40 both={both}/40 "
          f"y_stuck={len(yv_set)==1} c_stuck={len(cv_set)==1} "
          f"per_op={per_op}", flush=True)

    # ---- model vs reality on requested vectors ----
    vecs = []
    for arg in sys.argv[2:]:
        try:
            vecs.append(tuple(int(v) for v in arg.split(",")))
        except ValueError:
            pass
    if not vecs:
        vecs = [(3, 1, 0, 0)]
    for (op, a, bv, cin) in vecs:
        iv = {a_n: a, b_n: bv, cin_n: cin}
        for i in range(4):
            iv[op_n[i]] = (op >> i) & 1
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
        print(f"\nvector op={op} a={a} b={bv} cin={cin}: "
              f"want y={exp[nm(pb['y'][0])]} c={exp[nm(pb['cout'][0])]} "
              f"got y={1 if P(*y_pos)>0 else 0} "
              f"c={1 if P(*c_pos)>0 else 0}", flush=True)
        mism = tot = 0
        for net in sorted(placements.keys()):
            src = pl.net_sources[net]
            fp = refresh3d.feed_powers(net, placements[net], src,
                                       pl.net_sinks[net])
            for k, p in sorted(fp.items()):
                real = P(*k)
                want = exp.get(net, 0)
                # the model assumes a driven source (15); only nets the
                # vector actually DRIVES (want=1) are comparable
                if want != 1:
                    continue
                tot += 1
                if (p >= 1) != (real >= 1):
                    mism += 1
                    print(f"  MODEL MISMATCH {net} {k}: model={p} real={real} "
                          f"want={want}", flush=True)
        print(f"model-reality agree (want=1 only): {tot-mism}/{tot}",
              flush=True)


if __name__ == "__main__":
    main()
