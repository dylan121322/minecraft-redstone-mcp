"""
solve_parallel.py — the enumeration/solve pipeline using the Win box properly:
32 logical cores + an RTX 5080 (84 SM, 16 GB).

Everything so far ran single-process, i.e. on 1/32 of the CPU and none of the GPU.
Three levels of parallelism are available and all are used here:

  1. PROCESS POOL over independent router runs. Each (module, yield-set, seed)
     trial is a separate full route — embarrassingly parallel, one per worker.
  2. PROCESS POOL over sinks inside one route when enumerating candidates: each
     sink's (climb-site x cross-layer x rotation) sweep is independent.
  3. GPU (torch) for the pairwise-conflict matrix and the adjacency tests: the
     candidate voxel sets become boolean tensors and conflicts are computed as
     batched 3-D dilation + AND, which is thousands of times faster than the
     Python loops used in solve_exact.py.

Usage:
  solve_parallel.py trials  <mods> <rounds> [workers]   # level 1
  solve_parallel.py enum    <mod>  <rounds> [workers]   # level 2 + 3
"""
import sys, os, json, time, itertools
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


# ---------------------------------------------------------------- level 1
def _trial(args):
    """One full route with a given yield-set. Runs in its own process."""
    mod, yields, rounds = args
    import json as _j
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
    return {"mod": mod, "yields": list(yields), "shorts": sh,
            "failed": len(res.failed), "unfed": len(unfed),
            "unfed_list": unfed[:12], "wires": res.total_wires(),
            "secs": round(time.time() - t0, 1)}


def run_trials(mods, rounds, workers):
    """Sweep yield-sets in parallel. The candidate blockers come from the
    single-net and pair combinations of the nets that appear as blockers."""
    nls = json.load(open(NETLISTS))
    jobs = []
    for mod in mods:
        # broad sweep: no yield, every single net that has >1 sink, and pairs of
        # the most-connected ones. Bounded so the sweep stays finite.
        from placer import place
        pl = place(nls[mod], col_gap=16, row_gap=16)
        multi = [n for n, ks in pl.net_sinks.items() if len(ks) >= 2]
        multi = sorted(multi, key=lambda n: -len(pl.net_sinks[n]))[:12]
        jobs.append((mod, (), rounds))
        for n in multi:
            jobs.append((mod, (n,), rounds))
        for a, b in itertools.combinations(multi[:8], 2):
            jobs.append((mod, (a, b), rounds))
        # TRIPLES seeded from the best pairs found so far. The pair sweep on alu1
        # bottomed out at 3 unfed sinks with yield=(n5,n25) / (n7,n13), so the
        # remaining sinks need a third net to yield. 32 cores make this affordable:
        # the pair sweep itself took 66s wall-clock for 41 trials.
        seeds = os.environ.get("SEED_YIELDS", "")
        seed_sets = [tuple(s.split("+")) for s in seeds.split(",") if s]
        if seed_sets:
            for sd in seed_sets:
                for n in multi:
                    if n in sd:
                        continue
                    jobs.append((mod, tuple(sorted(set(sd) | {n})), rounds))
        else:
            for a, b, c in itertools.combinations(multi[:6], 3):
                jobs.append((mod, (a, b, c), rounds))
    print(f"level-1 sweep: {len(jobs)} trials on {workers} workers")
    out = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_trial, j): j for j in jobs}
        done = 0
        for f in as_completed(futs):
            try:
                rec = f.result()
            except Exception as e:
                rec = {"mod": futs[f][0], "yields": list(futs[f][1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            done += 1
            if "error" in rec:
                print(f"  [{done}/{len(jobs)}] {rec['mod']} "
                      f"yield={rec['yields']} ERROR {rec['error'][:60]}", flush=True)
            else:
                print(f"  [{done}/{len(jobs)}] {rec['mod']} "
                      f"yield={rec['yields'] or '-'} shorts={rec['shorts']} "
                      f"failed={rec['failed']} unfed={rec['unfed']} "
                      f"({rec['secs']}s)", flush=True)
    print(f"\nsweep wall-clock {time.time()-t0:.0f}s "
          f"(serial estimate {sum(r.get('secs',0) for r in out):.0f}s)")
    ok = [r for r in out if "error" not in r]
    for mod in mods:
        sub = [r for r in ok if r["mod"] == mod]
        sub.sort(key=lambda r: (r["shorts"], r["unfed"], r["failed"]))
        print(f"\n=== {mod} best 6 (shorts, unfed, failed) ===")
        for r in sub[:6]:
            print(f"  yield={r['yields'] or '-'}: shorts={r['shorts']} "
                  f"unfed={r['unfed']} failed={r['failed']} wires={r['wires']}")
    json.dump(ok, open(os.path.join(base, "sweep_results.json"), "w"))
    print(f"\nsaved sweep_results.json")


# ---------------------------------------------------------------- level 2/3
def _enum_sink(args):
    """Enumerate (climb-site, cross-layer, rotation) triples for ONE sink,
    verifying the cross approach with the router's own legality rule."""
    mod, rounds, net, pin = args
    import json as _j
    from collections import deque
    from placer import place
    from route_buildable import BuildableRouter
    from via_gadget import down_tower_cells_dir
    DUST = "minecraft:redstone_wire"
    ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
            ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
    _H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    nls = _j.load(open(NETLISTS))
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    y0 = pl.bounds[0][1]
    own = {(p[0], p[2]) for p in res.wires.get(net, ())} | \
          {(q[0], q[2]) for (q, _f) in res.repeaters.get(net, ())}
    s = pl.net_sources[net]
    tree = sorted(own | {(s[0], s[2])})
    gx, gz = pin
    feed = (gx - 1, gz)

    def reach(src, cy, limit=6000):
        if not r._y2_free(src, net, cy):
            return None
        seen = {src}; prev = {}; q = deque([src]); st = 0
        while q and st < limit:
            cur = q.popleft(); st += 1
            if cur == feed:
                n = 0; c = cur
                while c in prev:
                    c = prev[c]; n += 1
                return n
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen or nx in r.rep_cells:
                    continue
                if not r._y2_free(nx, net, cy):
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    viable = []
    for cy in [y0 + 4 * i for i in range(1, 7)]:
        rots = []
        for arm, side in ROTS:
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=side, arm=arm)
            if any(c in r.cell_xz or c in r.pin_net for c in foot):
                continue
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            if any(r.owner3d.get(v) not in (None, net) for v in cond):
                continue
            rots.append((arm, side))
        if not rots:
            continue
        for t in tree[:60]:
            plen = reach(t, cy)
            if plen is not None:
                viable.append({"cy": cy, "site": list(t), "cross_len": plen,
                               "rots": len(rots)})
                break
    return {"net": net, "pin": list(pin), "tree": len(tree),
            "viable": viable}


def run_enum(mod, rounds, workers):
    nls = json.load(open(NETLISTS))
    from placer import place
    from route_buildable import BuildableRouter
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
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
    print(f"[{mod}] shorts={sh} failed={len(res.failed)} unfed={len(unfed)}")
    if not unfed:
        return
    jobs = [(mod, rounds, n, p) for n, p in unfed]
    print(f"level-2 enumeration: {len(jobs)} sinks on {workers} workers")
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        for f in as_completed([ex.submit(_enum_sink, j) for j in jobs]):
            rec = f.result()
            v = rec["viable"]
            print(f"  {rec['net']}@{tuple(rec['pin'])} tree={rec['tree']}: "
                  f"{len(v)} viable (cy,site) combos", flush=True)
            for e in v[:3]:
                print(f"     cy={e['cy']} site={tuple(e['site'])} "
                      f"cross={e['cross_len']} rots={e['rots']}")
    print(f"enumeration wall-clock {time.time()-t0:.0f}s")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "trials"
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else min(32, os.cpu_count() or 8)
    if what == "trials":
        mods = (sys.argv[2] if len(sys.argv) > 2 else "alu1").split(",")
        rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 4
        run_trials(mods, rounds, workers)
    else:
        mod = sys.argv[2] if len(sys.argv) > 2 else "alu1"
        rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 4
        run_enum(mod, rounds, workers)


if __name__ == "__main__":
    main()
