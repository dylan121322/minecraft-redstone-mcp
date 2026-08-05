"""
diag_n14_fixed.py — y is stuck at 1 in EVERY configuration tried: 16 runs across
8 yield-sets x {baseline, staggered cells} all give y_ok=10, stuck=True. Even
staggering (which fully separates the two feed cells of a gate) changes nothing.

So the cause is configuration-independent. The deepest unfed nets in y's cone are
n14@(120,2) and n17@(174,2) — both fail regardless. Look at what is deterministic
about those two sinks: their gate, their neighbours, whether their feed cell can
be reached AT ALL on an empty board (no other nets placed).

The empty-board test is the key discriminator:
  reachable on an empty board -> other nets are the problem (competition)
  unreachable even alone      -> placer geometry makes it impossible
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

ORTH, DIAG = coupling.ORTH, coupling.DIAG
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


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
    nets_to_test = (sys.argv[1] if len(sys.argv) > 1 else "n14,n17").split(",")
    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)

    # what gate owns each target sink, and who drives the sibling input?
    for net in nets_to_test:
        print(f"\n=== {net} ===")
        print(f"  source={pl.net_sources.get(net)}  sinks={pl.net_sinks.get(net)}")
        for k in pl.net_sinks.get(net, []):
            gate = None
            for name, pc in pl.placed.items():
                if k in pc.input_pins.values():
                    gate = (name, pc)
            if gate:
                name, pc = gate
                sib = {p: v for p, v in pc.input_pins.items() if v != k}
                sibnet = None
                for sn, sks in pl.net_sinks.items():
                    if any(v in sks for v in sib.values()):
                        sibnet = sn
                print(f"  sink {k} -> {name} ({pc.gtype}) "
                      f"sibling input {sib} driven by {sibnet}")

    # EMPTY-BOARD test: route ONLY this net, nothing else competing
    print(f"\n=== empty-board routing (only the net itself) ===")
    for net in nets_to_test:
        r = RB.BuildableRouter(pl, margin=16)
        # restrict the router to a single net by trimming the placement view
        keep = {net}
        orig_once = r._route_once
        def only(nets, soft=False, verbose=False, _k=keep):
            return orig_once([n for n in nets if n in _k], soft=soft,
                             verbose=verbose)
        r._route_once = only
        res = r.route(verbose=False, max_rounds=3)
        wires = set(res.wires.get(net, ()))
        reps = {p for (p, _f) in res.repeaters.get(net, ())}
        torch = {p for p in res.torches if res.torch_nets.get(p) == net}
        wt = {p for (p, _b) in res.wall_torches
              if res.wall_torch_nets.get(p) == net}
        mine = wires | reps | torch | wt
        cols = {(p[0], p[2]) for p in mine}
        sup = {s for s in res.supports if (s[0], s[2]) in cols}
        vox = mine | sup
        src = pl.net_sources[net]
        seed = [v for v in vox
                if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
        comp = set(seed); dq = deque(seed)
        while dq:
            cur = dq.popleft()
            cand = [(cur[0]+d[0], cur[1], cur[2]+d[1]) for d in _H]
            cand += [(cur[0], cur[1]+1, cur[2]), (cur[0], cur[1]-1, cur[2])]
            for d in _H:
                cand.append((cur[0]+d[0], cur[1]+1, cur[2]+d[1]))
                cand.append((cur[0]+d[0], cur[1]-1, cur[2]+d[1]))
            for q in cand:
                if q in vox and q not in comp:
                    comp.add(q); dq.append(q)
        y0 = pl.bounds[0][1]
        bad = [(k[0], k[2]) for k in pl.net_sinks[net]
               if (k[0]-1, y0, k[2]) not in comp]
        verdict = ("competition with other nets" if not bad
                   else "IMPOSSIBLE even alone -> placer geometry")
        print(f"  {net}: alone -> failed={res.failed} vox={len(vox)} "
              f"comp={len(comp)} unfed={bad}  => {verdict}")


if __name__ == "__main__":
    main()
