"""
test_stagger_ab.py — A/B the staggered 2-input cells across ALL modules, in
parallel on the 32 cores.

The staggered cells are MCHPRS-verified 4/4 each (cell_stagger.py). The question
here is the ROUTING effect: separating the two input feed cells of every gate
should help every module, because that pin-adjacency was structural, not specific
to alu1.

For each module we run baseline and staggered, with and without the best known
yield-set, and report shorts / unfed sinks / wires.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _job(args):
    mod, stag, yields, rounds, col_gap, row_gap = args
    import json as _j, importlib
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
    pl = place(nls[mod], col_gap=col_gap, row_gap=row_gap)
    r = BuildableRouter(pl, margin=max(10, col_gap))
    ys = set(yields)
    if ys:
        orig = r._route_once
        def patched(nets, soft=False, verbose=False):
            head = [n for n in nets if n not in ys]
            tail = [n for n in nets if n in ys]
            return orig(head + tail, soft=soft, verbose=verbose)
        r._route_once = patched
    t0 = time.time()
    res = r.route(verbose=False, max_rounds=rounds)
    sh, _ = r._count_shorts(res)
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
    mn, mx = pl.bounds
    return {"mod": mod, "stag": stag, "yields": list(yields),
            "nets": nets, "shorts": sh, "failed": len(res.failed),
            "unfed": len(unfed), "unfed_list": unfed[:5],
            "wires": res.total_wires(),
            "bbox": [mx[0]-mn[0]+1, mx[2]-mn[2]+1],
            "secs": round(time.time()-t0, 1)}


def main():
    mods = (sys.argv[1] if len(sys.argv) > 1
            else "alu1,Control,ALU_Control,Mux2to1,ImmGen").split(",")
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    best_yield = {"alu1": ("n13", "n17", "n7", "n8")}
    jobs = []
    for mod in mods:
        for stag in (False, True):
            jobs.append((mod, stag, (), rounds, 16, 16))
            ys = best_yield.get(mod)
            if ys:
                jobs.append((mod, stag, ys, rounds, 16, 16))
    print(f"A/B staggered cells: {len(jobs)} runs on {workers} workers")
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
                j = futs[f]
                rec = {"mod": j[0], "stag": j[1], "yields": list(j[2]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            tag = "stag" if rec.get("stag") else "base"
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {tag} "
                      f"ERROR {rec['error'][:60]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {tag} "
                      f"yield={len(rec['yields'])} shorts={rec['shorts']} "
                      f"unfed={rec['unfed']}/{rec['nets']} "
                      f"wires={rec['wires']} ({rec['secs']}s)", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    print(f"\n{'module':12s} {'variant':6s} {'yield':5s} {'shorts':>6s} "
          f"{'unfed':>6s} {'failed':>6s} {'wires':>6s} {'bbox':>12s}")
    for mod in mods:
        for ys_len in (0, 4):
            for stag in (False, True):
                rs = [r for r in ok if r["mod"] == mod and r["stag"] == stag
                      and len(r["yields"]) == ys_len]
                for r in rs:
                    print(f"{mod:12s} {'stag' if stag else 'base':6s} "
                          f"{ys_len:5d} {r['shorts']:6d} {r['unfed']:6d} "
                          f"{r['failed']:6d} {r['wires']:6d} "
                          f"{str(r['bbox']):>12s}")
    json.dump(ok, open(os.path.join(base, "stagger_ab.json"), "w"))
    print("\nsaved stagger_ab.json")


if __name__ == "__main__":
    main()
