"""
scan_colgap.py — sweep col_gap across ALL combinational modules before fixing it.
alu1/Control alone suggested 10 beats 16 (17% less wire, same routed count), but
the wide modules (Forwarding 92 gates, ALU 197) carry far more traffic per channel
and may need a wider gap. Decide on full data, not two modules.

Reports per (module, col_gap): bbox, routed/total, shorts, wires, seconds.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter


def one(nl, cg, rg=16, rounds=2):
    pl = place(nl, col_gap=cg, row_gap=rg)
    mn, mx = pl.bounds
    r = BuildableRouter(pl, margin=max(10, cg))
    t0 = time.time()
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
    return {
        "col_gap": cg,
        "bbox_x": mx[0] - mn[0] + 1,
        "bbox_z": mx[2] - mn[2] + 1,
        "routed": nets - len(res.failed),
        "nets": nets,
        "shorts": shorts,
        "wires": res.total_wires(),
        "secs": round(time.time() - t0, 1),
    }


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or list(nls.keys())
    gaps = [int(a) for a in sys.argv[1:] if a.isdigit()] or [16, 12, 10, 8]
    print(f"{'module':12s} {'gap':>3s} {'bbox_x':>6s} {'routed':>8s} "
          f"{'shorts':>6s} {'wires':>6s} {'secs':>6s}")
    best = {}
    for mod in mods:
        for cg in gaps:
            try:
                r = one(nls[mod], cg)
            except Exception as e:
                print(f"{mod:12s} {cg:3d} ERROR {type(e).__name__}: {e}")
                continue
            print(f"{mod:12s} {cg:3d} {r['bbox_x']:6d} "
                  f"{str(r['routed'])+'/'+str(r['nets']):>8s} {r['shorts']:6d} "
                  f"{r['wires']:6d} {r['secs']:6.1f}", flush=True)
            # rank: routed desc, shorts asc, wires asc
            key = (-r["routed"], r["shorts"], r["wires"])
            if mod not in best or key < best[mod][0]:
                best[mod] = (key, cg, r)
    print("\n=== best col_gap per module (routed desc, shorts asc, wires asc) ===")
    for mod, (_k, cg, r) in best.items():
        print(f"  {mod:12s} gap={cg:3d} routed={r['routed']}/{r['nets']} "
              f"shorts={r['shorts']} wires={r['wires']}")


if __name__ == "__main__":
    main()
