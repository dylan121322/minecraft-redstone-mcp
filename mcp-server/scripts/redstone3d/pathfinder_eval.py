"""
pathfinder_eval.py — full validation chain for the PathFinder router:

    place -> PathFinder.route (negotiation + hard repair) -> 0-short placements
         -> BuildableRouter._materialize (repeater insertion on long runs,
            tower-aware connectivity check) -> BuildResult
         -> emit_blocks + nucleation -> MCHPRS 40-vector truth table

Reports: shorts (re-counted AFTER repeater insertion, which can disturb
adjacency), failed nets (connectivity), y_ok/c_ok/both/stuck, per-op.
"""
import sys, os, json, time
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


_W = {}


def _init_worker(pl, res, ticks, y_pos, c_pos):
    """Spawn initializer: the routed result is computed ONCE in the parent and
    shipped per worker (not per job)."""
    from build_from_route import emit_blocks as _emit
    import nucleation as _nuc
    _W["pl"] = pl
    _W["res"] = res
    _W["ticks"] = ticks
    _W["y_pos"] = y_pos
    _W["c_pos"] = c_pos
    _W["emit"] = _emit
    _W["nuc"] = _nuc


def _eval_one(iv):
    """One MCHPRS vector in a worker process (Windows spawn-safe)."""
    import nucleation as _nuc
    pl = _W["pl"]; res = _W["res"]
    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    _W["emit"](setter, pl, res, iv)
    sc = _W["nuc"].Schematic.create("t")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = _W["nuc"].MchprsWorld.create_with_options(sc, True, False)
    w.tick(_W["ticks"])
    yv = 1 if w.get_redstone_power(*_W["y_pos"]) > 0 else 0
    cv = 1 if w.get_redstone_power(*_W["c_pos"]) > 0 else 0
    return iv, yv, cv


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else 32
    ticks = int(sys.argv[4]) if len(sys.argv) > 4 else 80
    nls = json.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)

    # ---- single-process route + materialize for the shorts/failed report ----
    t0 = time.time()
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=rounds)
    print(f"PathFinder: shorts={shorts} ({time.time()-t0:.0f}s)", flush=True)

    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    print(f"materialized: failed={len(res.failed)} {res.failed[:8]} "
          f"wires={res.total_wires()} "
          f"reps={sum(len(v) for v in res.repeaters.values())}", flush=True)

    occ = {}
    for n, ws in res.wires.items():
        for p in ws:
            occ[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occ[q] = n
    for p in res.torches:
        occ[p] = res.torch_nets.get(p, "?")
    for (q, _b) in res.wall_torches:
        occ[q] = res.wall_torch_nets.get(q, "?")
    shorts = coupling.count_shorts(occ)
    print(f"post-materialize shorts = {shorts}", flush=True)

    # ---- parallel 40-vector MCHPRS truth table ----
    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))

    jobs = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    iv = {a_n: a, b_n: bv, cin_n: cin}
                    for i in range(4):
                        iv[op_n[i]] = (op >> i) & 1
                    for inet in nl["inputs"]:
                        iv.setdefault(inet, 0)
                    jobs.append(iv)

    ny = nc = both = 0
    yv_set = set(); cv_set = set()
    per_op = {}
    t1 = time.time()
    from concurrent.futures import ProcessPoolExecutor, as_completed
    with ProcessPoolExecutor(max_workers=workers,
                             initializer=_init_worker,
                             initargs=(pl, res, ticks, y_pos, c_pos)) as ex:
        futs = {ex.submit(_eval_one, iv): iv for iv in jobs}
        done = 0
        for f in as_completed(futs):
            iv, yv, cv = f.result()
            done += 1
            op = sum((iv[op_n[i]] & 1) << i for i in range(4))
            a, bv, cin = iv[a_n], iv[b_n], iv[cin_n]
            bb = (1 - bv) if op == 6 else bv
            summ = a ^ bb ^ cin
            cout = (a & bb) | (cin & (a ^ bb))
            ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv,
                  6: summ}.get(op, 0)
            ny += (yv == ey); nc += (cv == cout)
            both += (yv == ey and cv == cout)
            yv_set.add(yv); cv_set.add(cv)
            per_op[op] = per_op.get(op, 0) + (yv == ey and cv == cout)
            if done % 8 == 0:
                print(f"  [{done}/40] both={both} y={ny} c={nc} "
                      f"{time.time()-t1:.0f}s", flush=True)
    print(f"MCHPRS 40 vectors ({time.time()-t1:.0f}s):", flush=True)
    print(f"  y_ok={ny}/40  c_ok={nc}/40  both={both}/40  "
          f"y_stuck={len(yv_set)==1}  c_stuck={len(cv_set)==1}", flush=True)
    print(f"  per_op={per_op}", flush=True)


if __name__ == "__main__":
    main()
