"""
test_correct_model.py — run the router with the MEASURED coupling rule in the
legality checks (not just in the audit).

State of knowledge (all MCHPRS-measured):
  orthogonal / directly above-below      -> couples
  pure diagonal, no shared conductor     -> does NOT couple
  diagonal WITH a shared orthogonal conductor -> couples
So `shell8` (what the router uses) is too strict: it rejects diagonal pairs even
when nothing bridges them. `ortho` (4-neighbour) is too loose: it misses the
shared-cell path. Auditing the current 28/29 result showed shell8 reports 1 short
on alu1 that the correct rule says is not one — i.e. the router is already
throwing away legal placements.

This patches _foreign_plane (the hot predicate used by the y0 BFS, the extension,
the descent and the tower checks) to the correct rule and measures the effect.
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def _job(args):
    mod, yields, rounds, model = args
    import json as _j, importlib, time as _t
    import route_buildable as RB
    importlib.reload(RB)

    if model == "correct":
        def _foreign_plane(self, xz, net, owner):
            """Measured rule: orthogonal always couples; a diagonal couples only
            when one of the two shared orthogonal cells is itself occupied."""
            x, z = xz
            for dx, dz in ORTH:
                o = owner.get((x+dx, z+dz))
                if o is not None and o != net:
                    return True
            for dx, dz in DIAG:
                o = owner.get((x+dx, z+dz))
                if o is None or o == net:
                    continue
                if (x+dx, z) in owner or (x, z+dz) in owner:
                    return True
            return False
        RB.BuildableRouter._foreign_plane = _foreign_plane
    elif model == "ortho":
        RB._PLANE_SHELL = ORTH
        RB.BuildableRouter._SHELL3D = [(1, 0, 0), (-1, 0, 0), (0, 0, 1),
                                       (0, 0, -1), (0, 1, 0), (0, -1, 0)]

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

    # audit with the CORRECT rule regardless of which model routed
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
    seen = set()
    for p, net in occ.items():
        x, y, z = p
        for dx, dz in ORTH:
            q = (x+dx, y, z+dz); o = occ.get(q)
            if o is not None and o != net:
                seen.add(tuple(sorted([p, q])))
        for dy in (1, -1):
            q = (x, y+dy, z); o = occ.get(q)
            if o is not None and o != net:
                seen.add(tuple(sorted([p, q])))
        for dx, dz in DIAG:
            q = (x+dx, y, z+dz); o = occ.get(q)
            if o is None or o == net:
                continue
            if (x+dx, y, z) in occ or (x, y, z+dz) in occ:
                seen.add(tuple(sorted([p, q])))
    true_shorts = len(seen)

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
    return {"mod": mod, "model": model, "yields": list(yields), "nets": nets,
            "router_shorts": r._count_shorts(res)[0], "true_shorts": true_shorts,
            "failed": len(res.failed), "unfed": len(unfed),
            "unfed_list": unfed[:5], "wires": res.total_wires(),
            "secs": round(_t.time()-t0, 1)}


def main():
    mods = (sys.argv[1] if len(sys.argv) > 1
            else "alu1,Control,Mux2to1,ImmGen").split(",")
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    best = {"alu1": ("n13", "n17", "n7", "n8")}
    jobs = []
    for mod in mods:
        for model in ("shell8", "correct"):
            jobs.append((mod, (), rounds, model))
            if mod in best:
                jobs.append((mod, best[mod], rounds, model))
    print(f"coupling-model A/B: {len(jobs)} runs on {workers} workers")
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
                rec = {"mod": j[0], "model": j[3], "yields": list(j[1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {rec['model']:8s} "
                      f"ERROR {rec['error'][:60]}", flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] {rec['mod']:12s} {rec['model']:8s} "
                      f"y={len(rec['yields'])} true_shorts={rec['true_shorts']} "
                      f"unfed={rec['unfed']}/{rec['nets']} "
                      f"wires={rec['wires']} ({rec['secs']}s)", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    print(f"\n{'module':12s} {'model':8s} {'y':2s} {'router_sh':>9s} "
          f"{'TRUE_sh':>8s} {'unfed':>7s} {'wires':>6s}")
    for mod in mods:
        for ylen in (0, 4):
            for model in ("shell8", "correct"):
                for r in [x for x in ok if x["mod"] == mod
                          and x["model"] == model and len(x["yields"]) == ylen]:
                    print(f"{mod:12s} {model:8s} {ylen:2d} "
                          f"{r['router_shorts']:9d} {r['true_shorts']:8d} "
                          f"{str(r['unfed'])+'/'+str(r['nets']):>7s} "
                          f"{r['wires']:6d}")
    json.dump(ok, open(os.path.join(base, "correct_model_ab.json"), "w"))
    print("\nsaved correct_model_ab.json")


if __name__ == "__main__":
    main()
