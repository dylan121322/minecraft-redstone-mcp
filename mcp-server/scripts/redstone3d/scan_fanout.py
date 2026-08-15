"""
scan_fanout.py — 32-worker parallel sweep over the fanout express-lane
parameters (multiplier x via cost x layers), reporting shorts + strict-fed.
The best config's placements are scored without MCHPRS; the winner gets the
full truth-table run afterwards.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import coupling

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def run_one(args):
    rise, drop, p_cap, layers, fmult, rounds, mod = args
    t0 = time.time()
    import json as _j
    import pathfinder3d as PF
    from placer import place
    nls = _j.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = rise
    PF.DROP_COST = drop
    pf = PF.PathFinder3D(pl, margin=16, max_layers=layers, p_cap=p_cap,
                         fanout_mult=fmult)
    placements, _s = pf.route(max_rounds=rounds, verbose=False,
                              start_layers=layers - 1)
    occ3 = {}
    for n, ps in placements.items():
        for role, x, y, z, *rest in ps:
            if role != "support":
                occ3[(x, y, z)] = n
    shorts = coupling.count_shorts(occ3)
    unfed = [n for n in pf.nets
             if n not in placements or not pf._sink_fed(n, placements)]
    return dict(rise=rise, drop=drop, p_cap=p_cap, layers=layers,
                fmult=fmult, shorts=shorts, unfed=len(unfed),
                unfed_nets=sorted(unfed)[:6], nets=len(placements),
                secs=round(time.time() - t0, 1))


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    mod = sys.argv[2] if len(sys.argv) > 2 else "alu1"
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    configs = []
    for fmult in (0.0, 4.0, 8.0, 12.0, 20.0):
        for (rise, drop) in [(10, 8), (12, 10)]:
            for layers in (3, 4):
                configs.append((rise, drop, 128.0, layers, fmult, rounds, mod))
    print(f"{len(configs)} configs x {workers} workers", flush=True)
    t0 = time.time()
    from concurrent.futures import ProcessPoolExecutor, as_completed
    out = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_one, c): c for c in configs}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            done += 1
            out.append(r)
            print(f"  [{done}/{len(configs)}] fmult={r['fmult']:g} "
                  f"via={r['rise']}/{r['drop']} L={r['layers']} "
                  f"shorts={r['shorts']} unfed={r['unfed']} "
                  f"nets={r['nets']} ({r['secs']}s)", flush=True)
    out.sort(key=lambda r: (r["shorts"], r["unfed"]))
    print(f"\nwall-clock {time.time()-t0:.0f}s\nTOP 8:", flush=True)
    for r in out[:8]:
        print(f"  fmult={r['fmult']:g} via={r['rise']}/{r['drop']} "
              f"L={r['layers']} shorts={r['shorts']} unfed={r['unfed']} "
              f"{r['unfed_nets']}", flush=True)
    json.dump(out, open(os.path.join(base, "scan_fanout.json"), "w"))
    print("saved scan_fanout.json", flush=True)


if __name__ == "__main__":
    main()
