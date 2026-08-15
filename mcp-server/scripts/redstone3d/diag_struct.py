"""
diag_struct.py — after negotiation + drop-semantics repair, analyze the
residual shorts: are they pin-structural (fixed source/feed cells of two nets
that couple no matter what) or free-space (negotiable)?

Structural pairs are unfixable on the flat plane — they need a repeater feed
(repeater SIDES are isolated, measured P9) or a bridge. This tells us which.
"""
import sys, os, json, heapq
import coupling
import pathfinder as PF
from placer import place

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))


def repair_drop(pl, pf, placements):
    """Drop-semantics repair (the converging one)."""
    y0 = pf.y0

    def occ3_from(p):
        o = {}
        for net, ps in p.items():
            for role, x, y, z in ps:
                o[(x, y, z)] = net
        return o

    for _ in range(8):
        bad = pf._conflicting_nets(placements)
        if not bad:
            break
        frozen = {n: placements[n] for n in placements if n not in bad}
        fo3 = occ3_from(frozen)
        new_place = dict(frozen)
        still = set()
        for n in sorted(bad, key=lambda n: -len(pl.net_sinks[n])):
            ps = pf._hard_route_net(n, fo3)
            if ps is None:
                still.add(n)
                continue
            new_place[n] = ps
            for role, x, y, z in ps:
                fo3[(x, y, z)] = n
        placements = new_place
        if not still and pf._count_shorts_placements(placements) < 4:
            break
    return placements


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth",
                                      "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=False,
                                  with_repair=False)
    print(f"negotiation: {shorts}", flush=True)
    placements = repair_drop(pl, pf, placements)
    print(f"after repair: {pf._count_shorts_placements(placements)}", flush=True)

    y0 = pf.y0
    occ = pf._occ3_from(placements, y0)

    # fixed pins: sources and sink pins (the FEED cell k-1 is where dust must go)
    fixed = {}
    for net, pos in pl.net_sources.items():
        fixed[(pos[0], y0, pos[2])] = ("src", net)
    for net, ks in pl.net_sinks.items():
        for k in ks:
            fixed[(k[0] - 1, y0, k[2])] = ("feed", net)

    seen = set()
    struct = []
    free = []
    for p, net in occ.items():
        for dx, dy, dz in coupling.shell_offsets():
            q = (p[0] + dx, p[1] + dy, p[2] + dz)
            o = occ.get(q)
            if o is None or o == net:
                continue
            key = tuple(sorted([p, q]))
            if key in seen:
                continue
            seen.add(key)
            if coupling.couples(p, q, occ):
                # structural if EITHER cell is a fixed source/feed cell
                if p in fixed or q in fixed:
                    struct.append((p, net, q, o,
                                   fixed.get(p, ("?", "?")),
                                   fixed.get(q, ("?", "?"))))
                else:
                    free.append((p, net, q, o))
    print(f"residual shorts: structural={len(struct)} free={len(free)}",
          flush=True)
    for p, n1, q, n2, f1, f2 in struct:
        print(f"  STRUCT {n1}@{p} ({f1[0]}) <-> {n2}@{q} ({f2[0]}) "
              f"delta={tuple(q[i]-p[i] for i in range(3))}", flush=True)
    for p, n1, q, n2 in free[:12]:
        print(f"  FREE   {n1}@{p} <-> {n2}@{q}", flush=True)

    # for each structural pair: are the two FIXED cells themselves coupled?
    # (that would make any routing between them impossible on the plane)
    print("\nfixed-cell coupling check:", flush=True)
    fixed_list = list(fixed.items())
    for i in range(len(fixed_list)):
        p, (r1, n1) = fixed_list[i]
        for j in range(i + 1, len(fixed_list)):
            q, (r2, n2) = fixed_list[j]
            if n1 == n2:
                continue
            if coupling.couples(p, q, occ):
                print(f"  FIXED-COUPLED {n1}[{r1}]@{p} <-> {n2}[{r2}]@{q}",
                      flush=True)


if __name__ == "__main__":
    main()
