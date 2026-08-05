"""
test_rowgap.py — the last unfed sink on alu1 is a PLACEMENT problem, proven:

    n2  needs to feed (174,0,19)  -> its feed cell is (173,19)
    n17 must feed     (174,0,21)  -> its wire runs along z=20..21

Two different nets' pins sit 2 cells apart in the same column, and redstone dust
couples across 1 cell, so the single free row between them cannot serve both.
The router cannot fix that; the placement has to separate them.

Cells are depth=3 and are stacked with `row_gap` between them, so raising
row_gap increases the z distance between neighbouring gates' pins. This sweeps
row_gap (and col_gap, since a wider channel also helps the approach) with the
best known yield-set, in parallel across the 32 cores.
"""
import sys, os, json, time, itertools
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _job(args):
    mod, col_gap, row_gap, yields, rounds = args
    import json as _j
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
    mn, mx = pl.bounds
    return {"col_gap": col_gap, "row_gap": row_gap, "yields": list(yields),
            "shorts": sh, "failed": len(res.failed), "unfed": len(unfed),
            "unfed_list": unfed[:6], "wires": res.total_wires(),
            "bbox": [mx[0]-mn[0]+1, mx[2]-mn[2]+1],
            "secs": round(time.time()-t0, 1)}


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    yield_sets = [("n13", "n17", "n7", "n8"), ("n2", "n4", "n5", "n6"), ()]
    gaps = [(16, 16), (16, 20), (16, 24), (20, 20), (20, 24), (24, 24),
            (16, 18), (18, 22), (22, 22), (16, 28), (24, 28)]
    jobs = [(mod, cg, rg, ys, rounds)
            for (cg, rg) in gaps for ys in yield_sets]
    print(f"row/col-gap sweep: {len(jobs)} jobs on {workers} workers")
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
                rec = {"col_gap": j[1], "row_gap": j[2], "yields": list(j[3]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] cg={rec['col_gap']} rg={rec['row_gap']} "
                      f"ERROR {rec['error'][:50]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] cg={rec['col_gap']} rg={rec['row_gap']} "
                      f"yield={len(rec['yields'])} shorts={rec['shorts']} "
                      f"failed={rec['failed']} unfed={rec['unfed']} "
                      f"wires={rec['wires']} ({rec['secs']}s)", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s "
          f"(serial {sum(r.get('secs',0) for r in out):.0f}s)")
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (r["shorts"], r["unfed"], r["failed"], r["wires"]))
    print("\n=== best 10 ===")
    for r in ok[:10]:
        print(f"  cg={r['col_gap']} rg={r['row_gap']} yield={r['yields']}: "
              f"shorts={r['shorts']} unfed={r['unfed']} failed={r['failed']} "
              f"wires={r['wires']} bbox={r['bbox']}")
    perfect = [r for r in ok if r["shorts"] == 0 and r["unfed"] == 0]
    if perfect:
        print(f"\n*** FULLY ROUTED, 0 SHORTS: {len(perfect)} configuration(s) ***")
        for r in perfect[:5]:
            print(f"    cg={r['col_gap']} rg={r['row_gap']} yield={r['yields']} "
                  f"wires={r['wires']} bbox={r['bbox']}")
    json.dump(ok, open(os.path.join(base, "rowgap_results.json"), "w"))


if __name__ == "__main__":
    main()
