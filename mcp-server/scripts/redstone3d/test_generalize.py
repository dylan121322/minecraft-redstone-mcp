"""
test_generalize.py — run the router over EVERY combinational module, not just
alu1. The router has only ever been tuned on alu1 (24 gates); Control/ALU_Control
/Mux/ImmGen/Forwarding/ALU (up to 197 gates) have never been routed once, so this
is the first read on whether the algorithm generalises.

Reports per module: gates, nets, routed/failed, shorts, wires, bridges, towers,
and the wire/Manhattan ratio (compactness).
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter


def manhattan_lb(pl):
    tot = 0
    for n, ks in pl.net_sinks.items():
        s = pl.net_sources.get(n)
        if not s:
            continue
        for k in ks:
            tot += abs(s[0] - k[0]) + abs(s[2] - k[2])
    return tot


def run(mod, nl, rounds=4, col_gap=16, row_gap=16):
    t0 = time.time()
    pl = place(nl, col_gap=col_gap, row_gap=row_gap)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    lb = manhattan_lb(pl)
    nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
    mn, mx = pl.bounds
    return {
        "module": mod,
        "gates": len(nl["cells"]),
        "nets": nets,
        "routed": nets - len(res.failed),
        "failed": len(res.failed),
        "failed_nets": res.failed[:6],
        "shorts": shorts,
        "wires": res.total_wires(),
        "ratio": round(res.total_wires() / lb, 2) if lb else 0,
        "bridges": sum(res.bridges.values()),
        "towers": len(res.wall_torches) // 12,
        "bbox": (mx[0] - mn[0] + 1, mx[2] - mn[2] + 1),
        "secs": round(time.time() - t0, 1),
    }


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = sys.argv[1:] if len(sys.argv) > 1 else list(nls.keys())
    rows = []
    for mod in mods:
        try:
            row = run(mod, nls[mod])
        except Exception as e:
            row = {"module": mod, "error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    print("\n=== summary ===")
    hdr = f"{'module':12s} {'gates':>5s} {'nets':>5s} {'routed':>7s} {'shorts':>6s} {'wires':>6s} {'x/lb':>5s} {'secs':>5s}"
    print(hdr)
    for r in rows:
        if "error" in r:
            print(f"{r['module']:12s} ERROR {r['error'][:50]}")
            continue
        print(f"{r['module']:12s} {r['gates']:5d} {r['nets']:5d} "
              f"{str(r['routed'])+'/'+str(r['nets']):>7s} {r['shorts']:6d} "
              f"{r['wires']:6d} {r['ratio']:5.2f} {r['secs']:5.1f}")
    ok = [r for r in rows if "error" not in r and r["shorts"] == 0 and r["failed"] == 0]
    print(f"\nfully routed with 0 shorts: {len(ok)}/{len(rows)}")


if __name__ == "__main__":
    main()
