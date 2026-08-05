"""
sweep_measured.py — yield-set search under the MEASURED coupling rule.

Why this is the run that matters: auditing with the full measured rule showed the
old "alu1 28/29, 0 shorts" actually had 2 real shorts (shell8 never checked the
ramp / see-below cross-layer paths). Under the measured rule the only genuinely
clean alu1 result so far is 24/29 with the yield-set that had been tuned for
shell8. That yield-set is the wrong one for this model, so search again.

Objective, in strict order:
  1. true_shorts == 0        (a short makes the module compute wrong answers)
  2. fewest unfed sinks
  3. fewest wires
Staged (singles -> pairs -> triples -> quads), each stage seeded from the best of
the previous, 32 workers, one stage per invocation to keep ssh short.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _job(args):
    mod, yields, rounds = args
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

    import placer
    importlib.reload(placer)
    from placer import place
    nls = _j.load(open(NETLISTS))
    pl = place(nls[mod], col_gap=16, row_gap=16)
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
    true_shorts = coupling.count_shorts(occ)

    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0] - 1, k[2]) not in own.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
    return {"yields": list(yields), "true_shorts": true_shorts,
            "failed": len(res.failed), "unfed": len(unfed), "nets": nets,
            "unfed_list": unfed[:6], "wires": res.total_wires(),
            "secs": round(_t.time() - t0, 1)}


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

    multi = multi_sink_nets(mod)
    seeds = [tuple(s.split("+")) for s in seed_arg.split(",") if s]
    if stage == 1:
        jobs = [(mod, (), rounds)] + [(mod, (n,), rounds) for n in multi]
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
                jobs.append((mod, key, rounds))
    print(f"[{mod}] MEASURED model, stage {stage}: {len(jobs)} trials on "
          f"{workers} workers")
    out = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_job, j): j for j in jobs}
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
                      f"{rec['error'][:50]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] yield={rec['yields'] or '-'} "
                      f"true_sh={rec['true_shorts']} "
                      f"unfed={rec['unfed']}/{rec['nets']} "
                      f"wires={rec['wires']}", flush=True)
    ok = [r for r in out if "error" not in r]
    # shorts dominate, then unfed, then wires
    ok.sort(key=lambda r: (r["true_shorts"], r["unfed"], r["wires"]))
    print(f"\nstage wall-clock {time.time()-t0:.0f}s; best:")
    for r in ok[:6]:
        print(f"  yield={r['yields'] or '-'}: true_sh={r['true_shorts']} "
              f"unfed={r['unfed']}/{r['nets']} wires={r['wires']}")
    clean = [r for r in ok if r["true_shorts"] == 0]
    if clean:
        print(f"\n  ZERO-SHORT configs this stage: {len(clean)}")
        for r in clean[:5]:
            print(f"    yield={r['yields'] or '-'} unfed={r['unfed']}/{r['nets']} "
                  f"wires={r['wires']}")
    out_f = os.path.join(base, f"measured_{mod}_s{stage}.json")
    json.dump(ok, open(out_f, "w"))
    print(f"\nsaved {out_f}")
    print("TOP_SEEDS=" + ",".join("+".join(r["yields"])
                                  for r in ok[:4] if r["yields"]))


if __name__ == "__main__":
    main()
