"""
mix_diag.py — variable isolation: route ONCE (with_repair=False), then run
BOTH repair implementations on the SAME best solution:
  (a) pf.repair (the integrated method) and
  (b) the standalone replica from diag_repair.py.
If (a) fails and (b) succeeds on identical input, the integrated method has
a divergence from the replica. If both succeed, the with_repair=True path
in route() is the culprit.
"""
import sys, os, json, heapq
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "riscv_synth"))
import coupling
import pathfinder as PF
from placer import place

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
base = os.path.dirname(os.path.abspath(__file__))


def replica_repair(pl, pf, placements):
    """Standalone replica, verbatim from diag_repair.py."""
    y0 = pf.y0

    def usage_from(p):
        u = {}
        for net, ps in p.items():
            for role, x, y, z in ps:
                u.setdefault((x, z), set()).add(net)
        return u

    def occ3_from(p):
        o = {}
        for net, ps in p.items():
            for role, x, y, z in ps:
                o[(x, y, z)] = net
        return o

    def shorts_of(p):
        return coupling.count_shorts(occ3_from(p))

    def conflicting_nets(p):
        u = usage_from(p)
        o3 = occ3_from(p)
        bad = set()
        seen = set()
        for v, nets in u.items():
            x, z = v
            for dx, dz in ORTH + coupling.DIAG:
                w = (x + dx, z + dz)
                if w not in u:
                    continue
                if u[w] == nets:
                    continue
                a = (x, y0, z)
                b = (w[0], y0, w[1])
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                if coupling.couples(a, b, o3):
                    bad |= nets | u[w]
        return bad

    def hard_route_net(net, frozen_occ, frozen_usage):
        s = pl.net_sources[net]
        src = (s[0], s[2])
        tree = {src}
        for k in sorted(pl.net_sinks[net],
                        key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                        reverse=True):
            goal = (k[0] - 1, k[2])
            dist = {c: 0 for c in tree}
            prev = {}
            pq = [(0, c) for c in tree]
            heapq.heapify(pq)
            found = None
            while pq:
                d, cur = heapq.heappop(pq)
                if d > dist.get(cur, 1e9):
                    continue
                if cur == goal:
                    found = cur
                    break
                for dx, dz in ORTH:
                    nx = (cur[0] + dx, cur[1] + dz)
                    if nx != goal:
                        if not pf._in_box(nx):
                            continue
                        if nx in pf.cell_xz:
                            continue
                        if nx in pf.pin_xz:
                            continue
                    cand3 = (nx[0], y0, nx[1])
                    bad = False
                    for dx3, dy3, dz3 in coupling.shell_offsets():
                        q = (cand3[0] + dx3, cand3[1] + dy3, cand3[2] + dz3)
                        fo = frozen_occ.get(q)
                        if fo is not None and fo != net:
                            if coupling.couples(cand3, q, frozen_occ):
                                bad = True
                                break
                    if bad:
                        continue
                    nd = d + 1
                    if nd < dist.get(nx, 1e9):
                        dist[nx] = nd
                        prev[nx] = cur
                        heapq.heappush(pq, (nd, nx))
            if found is None:
                return None
            path = [found]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            for v in path:
                tree.add(v)
        return [("dust", v[0], y0, v[1]) for v in tree]

    for repair in range(6):
        bad = conflicting_nets(placements)
        if not bad:
            break
        frozen = {n: placements[n] for n in placements if n not in bad}
        fo3 = occ3_from(frozen)
        fu = usage_from(frozen)
        new_place = dict(frozen)
        still = set()
        for n in sorted(bad, key=lambda n: -len(pl.net_sinks[n])):
            ps = hard_route_net(n, fo3, fu)
            if ps is None:
                still.add(n)
                continue
            new_place[n] = ps
            for role, x, y, z in ps:
                fo3[(x, y, z)] = n
        placements = new_place
        if not still:
            if shorts_of(placements) == 0:
                break
    return placements, shorts_of(placements)


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth",
                                      "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=False,
                                  with_repair=False)
    print(f"negotiation shorts = {shorts}", flush=True)

    # (b) replica first on a copy
    import copy
    p_b = copy.deepcopy(placements)
    r_b, s_b = replica_repair(pl, pf, p_b)
    print(f"(b) replica repair -> shorts = {s_b}", flush=True)

    # (a) integrated method
    r_a = pf.repair(placements)
    s_a = pf._count_shorts_placements(r_a)
    print(f"(a) integrated repair -> shorts = {s_a}", flush=True)


if __name__ == "__main__":
    main()
