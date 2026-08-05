"""
test_stagger_mchprs.py — re-judge the STAGGERED cells on the truth table.

Why revisit: the structural root cause of y being stuck is now proven. Every
2-input gate has A and B two cells apart in z with the cell body between them, so
the two feed cells (x-1, z) and (x-1, z+2) share the single buffer cell between
them, and two different nets cannot both use it. x=42 alone has four such gates,
which is exactly where five nets fail.

Staggering input B one cell east separates the feed cells:
    original   feeds (x-1, z) and (x-1, z+2)  -> share (x-1, z+1)
    staggered  feeds (x-1, z) and (x  , z+2)  -> no shared cell
All four staggered cells are MCHPRS-verified 4/4 in isolation (cell_stagger.py).

The earlier A/B rejected staggering using STATIC counts (unfed sinks), which have
since been caught misreporting repeatedly. Judge it on the simulator instead.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _eval(args):
    mod, yields, rounds, stag, nvec, ticks = args
    import json as _j, importlib, time as _t
    import cell_library as clib
    importlib.reload(clib)
    if stag:
        import cell_library_stag as cls
        importlib.reload(cls)
        cls.install()
    import route_buildable as RB
    importlib.reload(RB)
    import coupling
    importlib.reload(coupling)
    ORTH, DIAG = coupling.ORTH, coupling.DIAG

    def _foreign_plane(self, xz, net, owner):
        x, z = xz
        for dx, dz in ORTH:
            o = owner.get((x + dx, z + dz))
            if o is not None and o != net:
                return True
        for dx, dz in DIAG:
            o = owner.get((x + dx, z + dz))
            if o is None or o == net:
                continue
            if (x + dx, z) in owner or (x, z + dz) in owner:
                return True
        return False
    SH = [(dx, 0, dz) for dx, dz in ORTH] + [(0, 1, 0), (0, -1, 0)] + \
         [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    RB.BuildableRouter._foreign_plane = _foreign_plane
    RB.BuildableRouter._SHELL3D = SH

    import placer, build_from_route
    importlib.reload(placer); importlib.reload(build_from_route)
    import nucleation as nuc
    from placer import place
    from build_from_route import emit_blocks

    nls = _j.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    ys = set(yields)
    if ys:
        orig = r._route_once
        def patched(nets, soft=False, verbose=False):
            head = [n for n in nets if n not in ys]
            tail = [n for n in nets if n in ys]
            return orig(head + tail, soft=soft, verbose=verbose)
        r._route_once = patched
    t0 = _t.time()
    res = r.route(verbose=False, max_rounds=rounds)

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

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))
    if not y_pos or not c_pos:
        return {"yields": list(yields), "stag": stag, "error": "no PO"}

    tests = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    tests.append((a, bv, cin, op))
    if nvec < len(tests):
        step = max(1, len(tests) // nvec)
        tests = tests[::step][:nvec]

    ok = ny = nc = 0
    yvals = set()
    for (a, bv, cin, op) in tests:
        iv = {a_n: a, b_n: bv, cin_n: cin}
        for i in range(4):
            iv[op_n[i]] = (op >> i) & 1
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
        w.tick(ticks)
        yv = 1 if w.get_redstone_power(*y_pos) > 0 else 0
        cv = 1 if w.get_redstone_power(*c_pos) > 0 else 0
        yvals.add(yv)
        bb = (1 - bv) if op == 6 else bv
        summ = a ^ bb ^ cin
        cout = (a & bb) | (cin & (a ^ bb))
        ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv, 6: summ}.get(op, 0)
        ny += (yv == ey); nc += (cv == cout)
        ok += (yv == ey and cv == cout)

    return {"yields": list(yields), "stag": stag, "passes": ok,
            "y_ok": ny, "c_ok": nc, "y_stuck": len(yvals) == 1,
            "vectors": len(tests), "shorts": shorts,
            "failed": len(res.failed), "wires": res.total_wires(),
            "secs": round(_t.time()-t0, 1)}


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    nvec = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    ticks = int(sys.argv[5]) if len(sys.argv) > 5 else 80
    yl = ["", "n8", "n5", "n3+n5", "n18+n8", "n13+n8", "n2", "n7"]
    jobs = []
    for y in yl:
        ys = tuple(t for t in y.split("+") if t)
        for st in (False, True):
            jobs.append((mod, ys, rounds, st, nvec, ticks))
    print(f"staggered-cells judged on the TRUTH TABLE: {len(jobs)} runs, "
          f"{nvec} vectors, {workers} workers")
    out = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_eval, j): j for j in jobs}
        n = 0
        for f in as_completed(futs):
            n += 1
            try:
                rec = f.result()
            except Exception as e:
                j = futs[f]
                rec = {"yields": list(j[1]), "stag": j[3],
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] y={rec['yields']} stag={rec['stag']} "
                      f"ERROR {rec['error'][:50]}", flush=True)
            else:
                lbl = "+".join(rec["yields"]) or "-"
                print(f"  [{n}/{len(jobs)}] y={lbl:10s} "
                      f"stag={int(rec['stag'])} "
                      f"PASS={rec['passes']}/{rec['vectors']} "
                      f"(y={rec['y_ok']}{'S' if rec['y_stuck'] else ' '} "
                      f"c={rec['c_ok']}) sh={rec['shorts']} "
                      f"failed={rec['failed']}", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (-r["passes"], r["shorts"], r["wires"]))
    print(f"\n{'yield':12s} {'stag':4s} {'PASS':>7s} {'y_ok':>5s} {'stuck':>5s} "
          f"{'c_ok':>5s} {'sh':>3s} {'fail':>4s} {'wires':>6s}")
    for r in ok:
        print(f"{'+'.join(r['yields']) or '-':12s} {int(r['stag']):4d} "
              f"{str(r['passes'])+'/'+str(r['vectors']):>7s} {r['y_ok']:5d} "
              f"{str(r['y_stuck']):>5s} {r['c_ok']:5d} {r['shorts']:3d} "
              f"{r['failed']:4d} {r['wires']:6d}")
    best_s = max((r for r in ok if r["stag"]), key=lambda r: r["passes"], default=None)
    best_b = max((r for r in ok if not r["stag"]), key=lambda r: r["passes"], default=None)
    if best_s and best_b:
        print(f"\nbest staggered: {best_s['passes']}/{best_s['vectors']} "
              f"(yield={best_s['yields']}, shorts={best_s['shorts']})")
        print(f"best baseline : {best_b['passes']}/{best_b['vectors']} "
              f"(yield={best_b['yields']}, shorts={best_b['shorts']})")
    json.dump(ok, open(os.path.join(base, "stagger_mchprs.json"), "w"))


if __name__ == "__main__":
    main()
