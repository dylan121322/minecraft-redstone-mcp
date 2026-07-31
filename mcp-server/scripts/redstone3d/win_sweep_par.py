"""
win_sweep_par.py — parallel parameter sweep for the Win box (9950X3D, 32 threads).

The serial sweep left 29 of 32 threads idle while the biggest modules (Forwarding
92 gates, ALU 197) took minutes each. Every (module, col_gap, rounds) combination
is independent — placement and routing share no state — so they fan out across
processes with no coordination.

Usage:
  E:\\py312\\python.exe win_sweep_par.py [--jobs N] [--mods A,B] [--gaps 16,12,10,8]
                                         [--rounds 1,2,4]
Each finished combination prints one JSON line, so progress is visible live.
"""
import sys, os, json, time, argparse
import multiprocessing as mp

BASE = os.path.dirname(os.path.abspath(__file__))


def _work(task):
    """Route one (module, col_gap, rounds). Imports happen inside the worker so
    each process builds its own module state."""
    mod, cg, rounds, rg = task
    sys.path.insert(0, BASE)
    sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))
    try:
        import json as _json
        from placer import place
        from route_buildable import BuildableRouter
        nls = _json.load(open(os.path.join(BASE, "..", "riscv_synth",
                                           "netlists.json")))
        nl = nls[mod]
        t0 = time.time()
        pl = place(nl, col_gap=cg, row_gap=rg)
        mn, mx = pl.bounds
        r = BuildableRouter(pl, margin=max(10, cg))
        res = r.route(verbose=False, max_rounds=rounds)
        shorts, _ = r._count_shorts(res)
        nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
        return {"module": mod, "col_gap": cg, "rounds": rounds, "row_gap": rg,
                "bbox_x": mx[0] - mn[0] + 1, "bbox_z": mx[2] - mn[2] + 1,
                "routed": nets - len(res.failed), "nets": nets,
                "shorts": shorts, "wires": res.total_wires(),
                "secs": round(time.time() - t0, 1)}
    except Exception as e:
        return {"module": mod, "col_gap": cg, "rounds": rounds,
                "error": f"{type(e).__name__}: {e}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--mods", default="")
    ap.add_argument("--gaps", default="16,12,10,8")
    ap.add_argument("--rounds", default="2")
    ap.add_argument("--rowgaps", default="16")
    args = ap.parse_args()

    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mods = [m for m in args.mods.split(",") if m] or list(nls.keys())
    gaps = [int(v) for v in args.gaps.split(",") if v]
    rounds = [int(v) for v in args.rounds.split(",") if v]
    rgs = [int(v) for v in args.rowgaps.split(",") if v]

    tasks = [(m, cg, rd, rg) for m in mods for cg in gaps
             for rd in rounds for rg in rgs]
    # longest modules first so the tail does not serialise at the end
    order = {m: i for i, m in enumerate(sorted(
        mods, key=lambda m: -len(nls[m]["cells"])))}
    tasks.sort(key=lambda t: order[t[0]])

    print(f"# {len(tasks)} combinations on {args.jobs} workers "
          f"({os.cpu_count()} threads available)", flush=True)
    t0 = time.time()
    rows = []
    with mp.Pool(processes=args.jobs) as pool:
        for r in pool.imap_unordered(_work, tasks):
            rows.append(r)
            print(json.dumps(r), flush=True)
    print(f"# done in {time.time()-t0:.0f}s", flush=True)

    print("\n=== best per module (routed desc, shorts asc, wires asc) ===",
          flush=True)
    best = {}
    for r in rows:
        if "error" in r:
            continue
        key = (-r["routed"], r["shorts"], r["wires"])
        if r["module"] not in best or key < best[r["module"]][0]:
            best[r["module"]] = (key, r)
    for m, (_k, r) in sorted(best.items()):
        print(f"  {m:12s} gap={r['col_gap']:3d} rounds={r['rounds']} "
              f"routed={r['routed']}/{r['nets']} shorts={r['shorts']} "
              f"wires={r['wires']} {r['secs']}s", flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
