"""
win_sweep.py — heavy parameter sweeps, meant to run on the Win box (idle, faster).
Covers two open questions at once:

  1. col_gap for the LARGE modules (Forwarding 92 gates, ALU 197). The small
     modules disagreed (alu1 10, Control 12, others 16), so the wide ones decide
     whether a single default is even possible.
  2. max_rounds. Mux2to1 scored 33/34 with 2 rounds but 24/34 with 4, which
     suggests the negotiated re-routing actively hurts. If 1 round is generally
     best, that is a free improvement everywhere.

Writes one JSON line per run so partial progress is readable while it works.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter


def one(nl, cg, rounds, rg=16):
    pl = place(nl, col_gap=cg, row_gap=rg)
    mn, mx = pl.bounds
    r = BuildableRouter(pl, margin=max(10, cg))
    t0 = time.time()
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    nets = len([n for n in pl.net_sinks if pl.net_sources.get(n)])
    return {"col_gap": cg, "rounds": rounds,
            "bbox_x": mx[0] - mn[0] + 1,
            "routed": nets - len(res.failed), "nets": nets,
            "shorts": shorts, "wires": res.total_wires(),
            "secs": round(time.time() - t0, 1)}


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mode = sys.argv[1] if len(sys.argv) > 1 else "rounds"
    if mode == "gap":
        mods = sys.argv[2:] or ["Forwarding", "ALU"]
        grid = [(cg, 2) for cg in (16, 12, 10, 8)]
    else:
        mods = sys.argv[2:] or ["alu1", "Control", "ALU_Control",
                                "Mux2to1", "ImmGen", "Forwarding"]
        grid = [(16, r) for r in (1, 2, 4)]
    for mod in mods:
        for cg, rounds in grid:
            try:
                r = one(nls[mod], cg, rounds)
                r["module"] = mod
                print(json.dumps(r), flush=True)
            except Exception as e:
                print(json.dumps({"module": mod, "col_gap": cg, "rounds": rounds,
                                  "error": f"{type(e).__name__}: {e}"}), flush=True)


if __name__ == "__main__":
    main()
