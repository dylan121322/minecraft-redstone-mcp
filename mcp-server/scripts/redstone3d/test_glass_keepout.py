"""
test_glass_keepout.py — does glass actually change the ROUTER's decisions?

The emitter now uses glass for passive supports, and the truth table is
identical (16/40). But the ROUTER itself never sees glass: its legality checks
(_descent_conflict, _y2_free, _free3d) still treat every column as if the
supports conduct, because they were written before glass existed.

The question that decides whether relaxing the checks helps: does any net
currently fail BECAUSE of a see-below/ramp check that glass would now make
obsolete? Measure by counting, per failed sink, how many of its candidate
deliveries are killed ONLY by the cross-layer (see-below/ramp) checks — if those
were relaxed, would the sink become routable?
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

ORTH, DIAG = coupling.ORTH, coupling.DIAG


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
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n3+n5").split("+"))
    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yields]
        tail = [n for n in nets if n in yields]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=5)

    # which supports would be glass? (same rule as the emitter)
    powered = set(res.power_blocks)
    glass = set()
    for (sx, sy, sz) in res.supports:
        if sy >= 2 or (sx, sy, sz) in powered:
            continue
        glass.add((sx, sy, sz))
    print(f"glass supports: {len(glass)} / {len(res.supports)}")

    # classify failed sinks: would their stair/tower deliveries now be legal
    # because the see-below checks are obsolete on glass columns?
    from collections import deque
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                unfed.append((n, (k[0], k[2])))
    print(f"unfed sinks: {len(unfed)} {unfed[:8]}")

    # For each unfed sink: how many of its stair/tower candidate columns pass
    # through glass-only territory below the cross plane?
    y0 = pl.bounds[0][1]
    glass_affected = 0
    for (n, (gx, gz)) in unfed:
        feed = (gx - 1, gz)
        # count glass supports in the 4 columns nearest the feed (its descent
        # corridor)
        nglass = sum(1 for (sx, sy, sz) in glass
                     if abs(sx - feed[0]) <= 2 and abs(sz - feed[1]) <= 2)
        if nglass:
            glass_affected += 1
        print(f"  {n}@({gx},{gz}): glass supports in corridor = {nglass}")
    print(f"\nsinks with glass in their corridor: {glass_affected}/{len(unfed)}")


if __name__ == "__main__":
    main()
