"""
diag_rejected.py — the congestion map shows ZERO real congestion (max 2 nets in
any 3x3). So failed sinks are not starved for space — the router's search is
rejecting legal paths. The prime suspect: _PLANE_SHELL still includes the four
DIAGONAL offsets, and measured physics says pure diagonals do NOT couple
(test_diagonal: diagonal alone = 0, only through a shared orthogonal cell).

Check each failed sink's surroundings: count how many of its candidate path cells
are rejected ONLY because a diagonal foreign wire sits there (which would be
legal under the measured rule).
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from placer import place

ORTH, DIAG = coupling.ORTH, coupling.DIAG
DIAG_ONLY = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def install_measured():
    def _foreign_plane(self, xz, net, owner):
        x, z = xz
        for dx, dz in ORTH:
            o = owner.get((x + dx, z + dz))
            if o is not None and o != net:
                return True
        for dx, dz in DIAG:
            o = owner.get((x + dx, z + dz))
            if o is None or o == net:
                continue
            if (x + dx, z) in owner or (x, z + dz) in owner:
                return True
        return False
    SH = [(dx, 0, dz) for dx, dz in ORTH] + [(0, 1, 0), (0, -1, 0)] + \
         [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    RB.BuildableRouter._foreign_plane = _foreign_plane
    RB.BuildableRouter._SHELL3D = SH


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    ys = set((sys.argv[2] if len(sys.argv) > 2 else "n3+n5").split("+"))
    install_measured()
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in ys]
        tail = [n for n in nets if n in ys]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=5)

    # who owns the y0 plane
    y0 = pl.bounds[0][1]
    owner0 = {}
    for n, ws in res.wires.items():
        for (x, y, z) in ws:
            if y == y0:
                owner0[(x, z)] = n
    for n, reps in res.repeaters.items():
        for ((x, y, z), _f) in reps:
            if y == y0:
                owner0[(x, z)] = n

    # failed sinks
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    failed = []
    for n, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(n):
            continue
        for k in ks:
            if (k[0]-1, k[2]) not in own.get(n, set()):
                failed.append((n, (k[0], k[2])))
    print(f"[{mod}] failed sinks: {len(failed)} {failed}")

    # for each failed sink: how many free cells around the feed are blocked
    # ONLY by a pure-diagonal foreign wire (legal under measured physics)?
    for (n, (gx, gz)) in failed:
        feed = (gx - 1, gz)
        diag_blocked = 0
        orth_blocked = 0
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (feed[0] + dx, feed[1] + dz)
            o = owner0.get(q)
            if o is not None and o != n:
                orth_blocked += 1
        for dx, dz in DIAG_ONLY:
            q = (feed[0] + dx, feed[1] + dz)
            o = owner0.get(q)
            if o is not None and o != n:
                diag_blocked += 1
        print(f"  {n}@({gx},{gz}) feed{feed}: orth_blocked={orth_blocked} "
              f"diag_only_blocked={diag_blocked}")


if __name__ == "__main__":
    main()
