"""
congestion_map.py — measure WHERE the routing congestion actually is, so the
placer can add white space ONLY there (the industry way), instead of globally
raising gaps (which we measured makes things worse: sparse sweep 11->20+ shorts).

Congestion metric per cell: how many DIFFERENT nets own a conductor in its
3x3 neighbourhood (same layer). Cells the router fought over show many distinct
owners nearby; quiet cells show one or none.

Output: a density map + the top congested gate placements, ready for the
congestion-aware placer (A).
"""
import sys, os, json
from collections import Counter, defaultdict
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from placer import place

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

    # owner map: (x,y,z) -> net, from the whole result
    occ = {}
    for n, ws in res.wires.items():
        for p in ws:
            occ[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occ[q] = n
    for p in res.torches:
        occ[p] = res.torch_nets.get(p, "?")
    for (q, _b) in res.wall_torches:
        occ[q] = res.wall_torch_nets.get(q, "?")

    # congestion per (x,z) on the y0 plane: distinct nets within 3x3
    y0 = pl.bounds[0][1]
    owner0 = {}
    for (x, y, z), n in occ.items():
        if y == y0:
            owner0[(x, z)] = n
    dens = Counter()
    for (x, z), n in owner0.items():
        nets = set()
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                o = owner0.get((x + dx, z + dz))
                if o is not None:
                    nets.add(o)
        dens[(x, z)] = len(nets)

    # top congested cells
    top = dens.most_common(30)
    print(f"[{mod}] cells with conductors: {len(owner0)}")
    print("top congested (x,z): distinct nets in 3x3")
    for (x, z), d in top[:20]:
        print(f"  ({x:4d},{z:4d}): {d} nets")

    # which GATES sit at/near the top congested cells?
    print("\ngates near congested cells:")
    seen = set()
    for (x, z), d in top:
        for name, pc in pl.placed.items():
            if name in seen:
                continue
            ox, oz = pc.origin[0], pc.origin[2]
            if abs(ox - x) <= 6 and abs(oz - z) <= 6:
                seen.add(name)
                print(f"  {name} ({pc.gtype}) at ({ox},{oz}) "
                      f"near congestion {d} nets @({x},{z})")

    # histogram of density
    hist = Counter(dens.values())
    print("\ndensity histogram (cells with k distinct nets nearby):")
    for k in sorted(hist):
        print(f"  k={k}: {hist[k]} cells")


if __name__ == "__main__":
    main()
