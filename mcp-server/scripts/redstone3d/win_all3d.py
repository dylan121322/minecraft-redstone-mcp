"""
win_all3d.py — per-net layer/repeater statistics for the 3-D router: which
nets ride which layers, how long their runs are, and whether long runs got
refresh repeaters. Decay suspects show up as long runs with no repeaters.
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import route_buildable as RB
from placer import place

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nets_want = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else set()
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 10.0
    PF.DROP_COST = 8.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0)
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts} nets={len(placements)}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    y0 = pf.y0

    print(f"{'net':6s} {'dust':>5s} {'reps':>4s}  layer histogram", flush=True)
    for net in sorted(placements):
        if nets_want and net not in nets_want:
            continue
        ps = placements[net]
        dust = sum(1 for p in ps if p[0] == "dust")
        reps = len(res.repeaters.get(net, []))
        hist = Counter(p[2] for p in ps if p[0] == "dust")
        # longest same-layer straight-run estimate per layer
        hl = {y: c for y, c in sorted(hist.items())}
        print(f"{net:6s} {dust:5d} {reps:4d}  {hl}", flush=True)
        # per-layer longest connected run (BFS depth) — the decay risk
        for y, c in hl.items():
            if c <= 2:
                continue
            cells = {(p[1], p[3]) for p in ps if p[0] == "dust" and p[2] == y}
            # BFS longest chain from any cell
            from collections import deque
            seen = set()
            longest = 0
            for c0 in cells:
                if c0 in seen:
                    continue
                dq = deque([(c0, 0)])
                seen.add(c0)
                mx = 0
                while dq:
                    cur, d = dq.popleft()
                    mx = max(mx, d)
                    for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx = (cur[0] + dx, cur[1] + dz)
                        if nx in cells and nx not in seen:
                            seen.add(nx)
                            dq.append((nx, d + 1))
                longest = max(longest, mx)
            flag = "  <<< long, no refresh?" if longest >= 15 else ""
            print(f"    y={y}: {c} cells, longest chain {longest}{flag}",
                  flush=True)


if __name__ == "__main__":
    main()
