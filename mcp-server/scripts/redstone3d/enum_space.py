"""
enum_space.py — size the ENUMERATION SPACE for the failing sinks.

The heuristic router makes local greedy choices and has hit four dead ends. The
alternative the user wants: bound a small space and ENUMERATE it on the GPU.
Before writing any GPU code we must know how big that space actually is.

Per failing sink the discrete choices are:
  * cross layer            : cy in {y0+4, +8, +12, ...}            (L options)
  * delivery mechanism     : staircase corridor | 2x2 down tower
  * staircase row offset   : dz in {0, ±1..±8}                     (17 options)
  * down-tower rotation    : 8 verified (arm, side) pairs
  * tower foothold / climb : the extension end + direction         (F options)
So one sink has roughly L * (17 + 8) * F candidate deliveries, and a set of k
failing sinks has that to the k-th power IF they interact — which they do (they
compete for the same cells).

This script measures L, F and k on the real placements so we can decide:
  - full joint enumeration (k small, product tractable) -> exact solve
  - or per-sink enumeration with conflict propagation   -> CP/SAT style
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    print(f"[{mod}] shorts={shorts} failed={len(res.failed)}: {res.failed}")

    # which SINKS are unfed (not just which nets)?
    own_by_net = {}
    for n in res.wires:
        own_by_net[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                        {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own_by_net.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    print(f"unfed sinks: {len(unfed)}")
    for n, k in unfed:
        print(f"   {n} -> {k}")

    # measure the per-sink option counts
    L = 6              # cross-layer attempts the router already tries
    DZ = 17            # staircase row offsets currently enumerated
    ROT = 8            # verified down-tower rotations
    print(f"\nper-sink discrete options ~= L({L}) * (DZ({DZ}) + ROT({ROT})) = "
          f"{L*(DZ+ROT)}")
    k = len(unfed)
    print(f"k = {k} unfed sinks")
    if k:
        per = L * (DZ + ROT)
        print(f"joint space = {per}^{k} = {per**k:.3e}" if k <= 8 else
              f"joint space = {per}^{k} (astronomical)")
        print(f"per-sink independent = {per*k} candidates (tractable, "
              f"needs conflict resolution between them)")

    # how much FREE space is there around each unfed sink? that bounds a
    # brute-force local search box
    cell_xz = r.cell_xz
    pins = set(r.pin_net)
    for n, (gx, gz) in unfed[:6]:
        free = 0
        R = 12
        for x in range(gx - R, gx + R + 1):
            for z in range(gz - R, gz + R + 1):
                c = (x, z)
                if c in cell_xz or c in pins:
                    continue
                if r.owner0.get(c) not in (None, n):
                    continue
                free += 1
        print(f"   {n}@({gx},{gz}): {free} free cells in a {2*R+1}^2 box "
              f"({free/(2*R+1)**2:.0%})")


if __name__ == "__main__":
    main()
