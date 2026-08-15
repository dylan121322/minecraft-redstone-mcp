"""
run_one_config.py <idx> <turn> <rise> <drop> <pcap> <layers> <fmult> <rounds>

One router config, one process: route -> materialize -> sequential MCHPRS
40-vector truth table -> placements_{idx}.json + result_{idx}.json.
NO process pools anywhere: a crashing worker can only lose its own config.
If result_{idx}.json already exists the config is SKIPPED (restart-safe).
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    idx = int(sys.argv[1])
    turn = float(sys.argv[2]); rise = float(sys.argv[3]); drop = float(sys.argv[4])
    pcap = float(sys.argv[5]); layers = int(sys.argv[6]); fmult = float(sys.argv[7])
    rounds = int(sys.argv[8])
    resf = os.path.join(base, f"result_{idx}.json")
    if os.path.exists(resf):
        print(f"#{idx} already done, skip", flush=True)
        return
    import pathfinder3d as PF
    import coupling
    import route_buildable as RB
    from placer import place
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.TURN_PEN = turn
    PF.RISE_COST = rise
    PF.DROP_COST = drop
    t0 = time.time()
    pf = PF.PathFinder3D(pl, margin=16, max_layers=layers, p_cap=pcap,
                         fanout_mult=fmult)
    placements, shorts = pf.route(max_rounds=rounds, verbose=False,
                                  start_layers=2)
    t_route = time.time() - t0
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
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
    post = coupling.count_shorts(occ)
    unfed = [n for n in pf.nets
             if n not in placements or not pf._sink_fed(n, placements)]

    # sequential MCHPRS
    import nucleation as nuc
    from build_from_route import emit_blocks
    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))

    def one(iv):
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

    dump = {"mod": "alu1", "placements": placements, "shorts": shorts,
            "rise": rise, "drop": drop, "fmult": fmult, "turn": turn,
            "rounds": rounds, "max_layers": layers, "p_cap": pcap,
            "col_gap": 16, "ticks": 80}
    with open(os.path.join(base, f"placements_{idx}.json"), "w") as fh:
        json.dump(dump, fh)
    result = dict(idx=idx, turn=turn, rise=rise, drop=drop, pcap=pcap,
                  layers=layers, fmult=fmult, shorts=shorts, post=post,
                  unfed=len(unfed), unfed_nets=sorted(unfed)[:6],
                  failed=len(res.failed), route_s=round(t_route, 0),
                  mchprs_s=round(time.time() - t0 - t_route, 0),
                  y_ok=ny, c_ok=nc, both=both,
                  y_stuck=len(yv_set) == 1, c_stuck=len(cv_set) == 1,
                  per_op=per_op)
    with open(resf, "w") as fh:
        json.dump(result, fh)
    print(f"#{idx} done: shorts={shorts} post={post} unfed={len(unfed)} "
          f"both={both}/40 y={ny} c={nc} y_stuck={result['y_stuck']} "
          f"c_stuck={result['c_stuck']} route={t_route:.0f}s "
          f"mchprs={result['mchprs_s']:.0f}s per_op={per_op}", flush=True)


if __name__ == "__main__":
    main()
