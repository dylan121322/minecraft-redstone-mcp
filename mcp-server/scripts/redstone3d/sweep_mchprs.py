"""
sweep_mchprs.py — search yield-sets with the MCHPRS TRUTH TABLE as the objective.

Why the change: every static metric has now been caught lying at least once.
  * "0 shorts" under the 8-neighbour shell missed the ramp/see-below coupling
  * "29/29 routed" counted an isolated wire at a feed cell as fed
  * fixing connectivity to include tower structure dropped failed 13 -> 4 yet
    MCHPRS got WORSE (4/8 -> 1/8)
That last inversion is decisive: connectivity is not equivalence for conduction
(it ignores repeater orientation, torch parity and signal decay). So optimise
against the simulator directly.

Objective, strict order:
  1. truth-table passes (maximise)
  2. interfering pairs under the measured rule (minimise; a short is still fatal)
  3. wires (minimise)

Each trial routes, emits, builds a MCHPRS world per test vector and reads the two
outputs. ~1s per vector, so a subset of vectors is used while searching and the
best candidates are re-checked on the full 40.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _eval(args):
    """Route with a yield-set, then score with MCHPRS."""
    mod, yields, rounds, nvec, ticks = args
    import json as _j, importlib, time as _t
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
        return {"yields": list(yields), "error": "no PO"}

    tests = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    tests.append((a, bv, cin, op))
    # spread the sampled vectors across ops instead of taking a prefix
    if nvec < len(tests):
        step = max(1, len(tests) // nvec)
        tests = tests[::step][:nvec]

    ok = 0
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
        bb = (1 - bv) if op == 6 else bv
        summ = a ^ bb ^ cin
        cout = (a & bb) | (cin & (a ^ bb))
        ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv, 6: summ}.get(op, 0)
        ok += (yv == ey and cv == cout)

    return {"yields": list(yields), "passes": ok, "vectors": len(tests),
            "shorts": shorts, "failed": len(res.failed),
            "wires": res.total_wires(), "secs": round(_t.time() - t0, 1)}


def multi_sink_nets(mod, top=12):
    from placer import place
    nls = json.load(open(NETLISTS))
    pl = place(nls[mod], col_gap=16, row_gap=16)
    multi = [n for n, ks in pl.net_sinks.items() if len(ks) >= 2]
    return sorted(multi, key=lambda n: -len(pl.net_sinks[n]))[:top]


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    stage = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    seed_arg = sys.argv[5] if len(sys.argv) > 5 else ""
    nvec = int(sys.argv[6]) if len(sys.argv) > 6 else 10
    ticks = int(sys.argv[7]) if len(sys.argv) > 7 else 80

    multi = multi_sink_nets(mod)
    seeds = [tuple(s.split("+")) for s in seed_arg.split(",") if s]
    if stage == 1:
        jobs = [(mod, (), rounds, nvec, ticks)] + \
               [(mod, (n,), rounds, nvec, ticks) for n in multi]
    else:
        jobs = []; seen = set()
        for sd in seeds:
            for n in multi:
                if n in sd:
                    continue
                key = tuple(sorted(set(sd) | {n}))
                if key in seen:
                    continue
                seen.add(key)
                jobs.append((mod, key, rounds, nvec, ticks))
    print(f"[{mod}] MCHPRS-driven sweep, stage {stage}: {len(jobs)} trials, "
          f"{nvec} vectors each, {workers} workers")
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
                rec = {"yields": list(futs[f][1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] {rec['yields']} ERROR "
                      f"{rec['error'][:60]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] yield={rec['yields'] or '-'} "
                      f"PASS={rec['passes']}/{rec['vectors']} "
                      f"shorts={rec['shorts']} failed={rec['failed']} "
                      f"wires={rec['wires']}", flush=True)
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (-r["passes"], r["shorts"], r["wires"]))
    print(f"\nstage wall-clock {time.time()-t0:.0f}s; best by TRUTH TABLE:")
    for r in ok[:6]:
        print(f"  yield={r['yields'] or '-'}: PASS={r['passes']}/{r['vectors']} "
              f"shorts={r['shorts']} failed={r['failed']} wires={r['wires']}")
    out_f = os.path.join(base, f"mchprs_{mod}_s{stage}.json")
    json.dump(ok, open(out_f, "w"))
    print(f"\nsaved {out_f}")
    print("TOP_SEEDS=" + ",".join("+".join(r["yields"])
                                  for r in ok[:4] if r["yields"]))


if __name__ == "__main__":
    main()
