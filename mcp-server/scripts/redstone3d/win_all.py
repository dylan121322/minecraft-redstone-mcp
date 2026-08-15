"""
win_all.py — one-shot combo diagnosis:
  1. full repair log (every round: bad/dropped/shorts)
  2. which nets ended WITHOUT placements (dropped & soft-repair failed)
  3. wire length histogram (signal-decay risk)
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder as PF
import route_buildable as RB
from placer import place

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=True)
    print(f"FINAL shorts={shorts} nets_with_wires={len(placements)}/29",
          flush=True)
    missing = [n for n in pf.nets if n not in placements]
    print(f"nets WITHOUT wires: {sorted(missing)}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    print(f"materialize failed={res.failed}", flush=True)
    print("wire lengths (dust cells) + repeaters:", flush=True)
    for n in sorted(placements):
        nd = len(placements[n])
        nr = len(res.repeaters.get(n, []))
        flag = "  <<< no rep, long" if nd > 20 and nr == 0 else ""
        print(f"  {n:6s} dust={nd:4d} reps={nr:2d}{flag}", flush=True)


if __name__ == "__main__":
    main()
