"""
test_orthogonal_only.py — measure the effect of the CORRECTED coupling model.

MCHPRS proof (test_diagonal.py): redstone dust does NOT couple diagonally.
  orthogonal neighbour -> conducts (13)
  diagonal neighbour   -> 0, even with both orthogonal go-betweens empty
  two parallel lines 2 apart in z with one free row -> completely isolated

Yet route_buildable's _PLANE_SHELL includes the four diagonals, and every
legality test (_foreign_plane, _foreign_pin_adj, _y2_free, _descent_conflict,
_free3d) plus the _count_shorts audit treats a diagonal pair as a short. That
rejects legal geometry — and the alu1 blocker (n17 vs n2's feed) was largely
DIAGONAL adjacency.

This runs the sweep with the shell reduced to the 4 orthogonal offsets and
compares. Nothing else changes, so the delta is attributable.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _job(args):
    mod, yields, rounds, ortho = args
    import json as _j, importlib, time as _t
    import route_buildable as RB
    importlib.reload(RB)
    if ortho:
        # dust couples ONLY orthogonally (MCHPRS-verified); drop the diagonals
        RB._PLANE_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        RB.BuildableRouter._SHELL3D = [(1, 0, 0), (-1, 0, 0),
                                       (0, 0, 1), (0, 0, -1),
                                       (0, 1, 0), (0, -1, 0)]
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
    return {"mod": mod, "ortho": ortho, "yields": list(yields), "nets": nets,
            "shorts": sh, "failed": len(res.failed), "unfed": len(unfed),
            "unfed_list": unfed[:6], "wires": res.total_wires(),
            "secs": round(_t.time()-t0, 1)}


def main():
    mods = (sys.argv[1] if len(sys.argv) > 1
            else "alu1,Control,Mux2to1,ImmGen").split(",")
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    best = {"alu1": ("n13", "n17", "n7", "n8")}
    jobs = []
    for mod in mods:
        for ortho in (False, True):
            jobs.append((mod, (), rounds, ortho))
            if mod in best:
                jobs.append((mod, best[mod], rounds, ortho))
    print(f"orthogonal-only A/B: {len(jobs)} runs on {workers} workers")
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
                rec = {"mod": j[0], "ortho": j[3], "yields": list(j[1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            tag = "ORTHO" if rec.get("ortho") else "shell8"
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {tag:6s} ERROR "
                      f"{rec['error'][:60]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {tag:6s} "
                      f"yield={len(rec['yields'])} shorts={rec['shorts']} "
                      f"unfed={rec['unfed']}/{rec['nets']} wires={rec['wires']} "
                      f"({rec['secs']}s)", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    print(f"\n{'module':12s} {'shell':7s} {'yield':5s} {'shorts':>6s} "
          f"{'unfed':>7s} {'failed':>6s} {'wires':>6s}")
    for mod in mods:
        for ylen in (0, 4):
            for ortho in (False, True):
                for r in [x for x in ok if x["mod"] == mod
                          and x["ortho"] == ortho and len(x["yields"]) == ylen]:
                    print(f"{mod:12s} {'ORTHO' if ortho else 'shell8':7s} "
                          f"{ylen:5d} {r['shorts']:6d} "
                          f"{str(r['unfed'])+'/'+str(r['nets']):>7s} "
                          f"{r['failed']:6d} {r['wires']:6d}")
    json.dump(ok, open(os.path.join(base, "ortho_ab.json"), "w"))
    print("\nsaved ortho_ab.json")


if __name__ == "__main__":
    main()
