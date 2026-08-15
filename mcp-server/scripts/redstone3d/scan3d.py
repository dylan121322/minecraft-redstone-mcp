"""
scan3d.py — parallel parameter sweep over the 3-D router. Each worker runs
route+repair with one configuration (no MCHPRS — that only runs on the best
result). 32 workers saturate the Win CPU; every worker is single-threaded.

Score = (shorts, missing_nets); the winner's placements are dumped to
best3d.json for the MCHPRS verification pass.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import coupling

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def run_one(args):
    rise, drop, rounds, p_cap, layers, start_layers, mod = args
    t0 = time.time()
    import json as _j
    import pathfinder3d as PF
    from placer import place
    nls = _j.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = rise
    PF.DROP_COST = drop
    pf = PF.PathFinder3D(pl, margin=16, max_layers=layers, p_cap=p_cap)
    placements, _s = pf.route(max_rounds=rounds, verbose=False,
                              start_layers=start_layers)
    occ3 = {}
    for n, ps in placements.items():
        for role, x, y, z, *rest in ps:
            if role != "support":
                occ3[(x, y, z)] = n
    shorts = coupling.count_shorts(occ3)
    missing = [n for n in pf.nets if n not in placements]
    return dict(rise=rise, drop=drop, rounds=rounds, p_cap=p_cap,
                layers=layers, start_layers=start_layers, shorts=shorts,
                missing=len(missing), missing_nets=sorted(missing),
                nets=len(placements), secs=round(time.time() - t0, 1))


def main():
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 32
    mod = sys.argv[2] if len(sys.argv) > 2 else "alu1"
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 30
    # refined sweep around the best point (rise=10/drop=8/L=3 -> 38 shorts):
    # include L=4 to test another layer, and fine via-cost steps.
    configs = []
    for (rise, drop) in [(10, 8), (9, 7), (11, 9), (10, 7), (9, 8), (11, 8)]:
        for p_cap in (96.0, 128.0, 192.0):
            for layers in (3, 4):
                # start one layer below max (the top layer is what matters)
                configs.append((rise, drop, rounds, p_cap, layers,
                                layers - 1, mod))
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
            print(f"  [{done}/{len(configs)}] rise={r['rise']} "
                  f"drop={r['drop']} pcap={r['p_cap']:g} L={r['layers']} "
                  f"shorts={r['shorts']} missing={r['missing']} "
                  f"nets={r['nets']} ({r['secs']}s)", flush=True)
    out.sort(key=lambda r: (r["shorts"], r["missing"]))
    print(f"\nwall-clock {time.time()-t0:.0f}s\nTOP 10:", flush=True)
    for r in out[:10]:
        print(f"  rise={r['rise']} drop={r['drop']} pcap={r['p_cap']:g} "
              f"L={r['layers']} shorts={r['shorts']} missing={r['missing']} "
              f"{r['missing_nets'][:5]}", flush=True)
    json.dump(out, open(os.path.join(base, "scan3d.json"), "w"))
    print("saved scan3d.json", flush=True)


if __name__ == "__main__":
    main()
