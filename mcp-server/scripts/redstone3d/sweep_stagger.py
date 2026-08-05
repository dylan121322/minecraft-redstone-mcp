"""
sweep_stagger.py — give the STAGGERED cell layout its own yield-set search.

The first A/B was unfair: it evaluated the staggered layout with the yield-set
(n13+n17+n7+n8) that had been tuned for the ORIGINAL pin coordinates. Staggering
moves every input B one cell east, so all pin positions — and therefore which
nets contend — change. The staggered layout has to be tuned from scratch.

Same iterative scheme that took the original layout from 9 unfed to 1:
  round 1: no yield + every multi-sink net alone
  round 2: pairs seeded from the best singles
  round 3: triples seeded from the best pairs
  round 4: quads
All in parallel over the 32 cores.
"""
import sys, os, json, time, itertools
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _job(args):
    mod, yields, rounds, stag = args
    import json as _j, importlib, time as _t
    import cell_library as clib
    importlib.reload(clib)
    if stag:
        import cell_library_stag as cls
        importlib.reload(cls)
        cls.install()
    import placer, route_buildable
    importlib.reload(placer); importlib.reload(route_buildable)
    from placer import place
    from route_buildable import BuildableRouter
    nls = _j.load(open(NETLISTS))
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
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
    sh, _x = r._count_shorts(res)
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
    return {"yields": list(yields), "shorts": sh, "failed": len(res.failed),
            "unfed": len(unfed), "unfed_list": unfed[:6], "nets": nets,
            "wires": res.total_wires(), "secs": round(_t.time()-t0, 1)}


def multi_sink_nets(mod, stag, top=12):
    import importlib
    import cell_library as clib
    importlib.reload(clib)
    if stag:
        import cell_library_stag as cls
        importlib.reload(cls)
        cls.install()
    import placer
    importlib.reload(placer)
    from placer import place
    nls = json.load(open(NETLISTS))
    pl = place(nls[mod], col_gap=16, row_gap=16)
    multi = [n for n, ks in pl.net_sinks.items() if len(ks) >= 2]
    return sorted(multi, key=lambda n: -len(pl.net_sinks[n]))[:top]


def run_stage(mod, jobs, workers, label):
    print(f"\n--- {label}: {len(jobs)} trials on {workers} workers ---")
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
                      f"shorts={rec['shorts']} unfed={rec['unfed']}/{rec['nets']} "
                      f"wires={rec['wires']}", flush=True)
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (r["shorts"], r["unfed"], r["failed"], r["wires"]))
    print(f"  stage wall-clock {time.time()-t0:.0f}s; best:")
    for r in ok[:5]:
        print(f"    yield={r['yields'] or '-'}: shorts={r['shorts']} "
              f"unfed={r['unfed']} failed={r['failed']} wires={r['wires']}")
    return ok


def main():
    """Stages can be run one at a time (arg 5 = stage number) so a single ssh
    invocation stays short. Background launching via powershell Start-Process was
    tried and DEADLOCKS: a hidden window has no console handles for
    ProcessPoolExecutor to hand to its workers, so the pool never starts (log
    froze at stage 1, one process left spinning). Foreground ssh works, hence
    per-stage runs with the seeds passed in."""
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    stag = (sys.argv[4] if len(sys.argv) > 4 else "1") == "1"
    only_stage = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    seed_arg = sys.argv[6] if len(sys.argv) > 6 else ""

    if only_stage:
        multi = multi_sink_nets(mod, stag)
        seeds = [tuple(s.split("+")) for s in seed_arg.split(",") if s]
        if only_stage == 1:
            jobs = [(mod, (), rounds, stag)] + \
                   [(mod, (n,), rounds, stag) for n in multi]
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
                    jobs.append((mod, key, rounds, stag))
        res = run_stage(mod, jobs, workers, f"stage {only_stage}")
        tag = "stag" if stag else "base"
        out = os.path.join(base, f"sweep_{mod}_{tag}_s{only_stage}.json")
        json.dump(res, open(out, "w"))
        print(f"\nsaved {out}")
        print("TOP_SEEDS=" + ",".join(
            "+".join(r["yields"]) for r in res[:4] if r["yields"]))
        return
    print(f"[{mod}] staggered={stag} rounds={rounds} workers={workers}")
    multi = multi_sink_nets(mod, stag)
    print(f"multi-sink nets: {multi}")

    # stage 1: singles
    jobs = [(mod, (), rounds, stag)] + [(mod, (n,), rounds, stag) for n in multi]
    s1 = run_stage(mod, jobs, workers, "stage 1 (singles)")
    best_singles = [tuple(r["yields"]) for r in s1[:4] if r["yields"]]

    # stage 2: pairs seeded from the best singles
    seeds = best_singles or [(multi[0],)]
    jobs = []
    seen = set()
    for sd in seeds:
        for n in multi:
            if n in sd:
                continue
            key = tuple(sorted(set(sd) | {n}))
            if key in seen:
                continue
            seen.add(key)
            jobs.append((mod, key, rounds, stag))
    s2 = run_stage(mod, jobs, workers, "stage 2 (pairs)")
    best_pairs = [tuple(r["yields"]) for r in s2[:4] if r["yields"]]

    # stage 3: triples
    jobs = []; seen = set()
    for sd in best_pairs:
        for n in multi:
            if n in sd:
                continue
            key = tuple(sorted(set(sd) | {n}))
            if key in seen:
                continue
            seen.add(key)
            jobs.append((mod, key, rounds, stag))
    s3 = run_stage(mod, jobs, workers, "stage 3 (triples)")
    best_triples = [tuple(r["yields"]) for r in s3[:4] if r["yields"]]

    # stage 4: quads
    jobs = []; seen = set()
    for sd in best_triples:
        for n in multi:
            if n in sd:
                continue
            key = tuple(sorted(set(sd) | {n}))
            if key in seen:
                continue
            seen.add(key)
            jobs.append((mod, key, rounds, stag))
    s4 = run_stage(mod, jobs, workers, "stage 4 (quads)")

    allr = s1 + s2 + s3 + s4
    allr.sort(key=lambda r: (r["shorts"], r["unfed"], r["failed"], r["wires"]))
    print(f"\n=== OVERALL BEST ({'staggered' if stag else 'baseline'}) ===")
    for r in allr[:8]:
        print(f"  yield={r['yields'] or '-'}: shorts={r['shorts']} "
              f"unfed={r['unfed']}/{r['nets']} failed={r['failed']} "
              f"wires={r['wires']}")
    perfect = [r for r in allr if r["shorts"] == 0 and r["unfed"] == 0]
    if perfect:
        print(f"\n*** FULLY ROUTED 0 SHORTS: {len(perfect)} config(s) ***")
        for r in perfect[:5]:
            print(f"    yield={r['yields']} wires={r['wires']}")
    tag = "stag" if stag else "base"
    json.dump(allr, open(os.path.join(base, f"sweep_{mod}_{tag}.json"), "w"))
    print(f"\nsaved sweep_{mod}_{tag}.json")


if __name__ == "__main__":
    main()
