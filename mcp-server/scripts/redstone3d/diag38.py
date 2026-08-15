"""
diag38.py — diagnose the residual 38 shorts at the best sweep point
(rise=10/drop=8/L=3): which net pairs, where, and whether any involve the
FIXED cells (sources / sink feeds / PI injectors) — fixed-cell conflicts are
structural and need a placer/cell change, not a router change.
"""
import sys, os, json, time
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import coupling
from placer import place

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 10.0
    PF.DROP_COST = 8.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0)
    t0 = time.time()
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts} nets={len(placements)} "
          f"({time.time()-t0:.0f}s)", flush=True)

    occ3 = {}
    for n, ps in placements.items():
        for role, x, y, z, *rest in ps:
            if role != "support":
                occ3[(x, y, z)] = n

    # fixed cells: sources (published), sink feed cells, PI injectors
    fixed = {}
    for net, pos in pl.net_sources.items():
        fixed[pos] = ("src", net)
    for net, ks in pl.net_sinks.items():
        for k in ks:
            fixed[(k[0] - 1, pf.y0, k[2])] = ("feed", net)
    for net, pos in pl.primary_inputs.items():
        fixed[pos] = ("pi", net)
        fixed[(pos[0] - 1, pos[1], pos[2])] = ("inj", net)

    pairs = Counter()
    struct = 0
    free = 0
    seen = set()
    details = []
    for v, net in occ3.items():
        for dx, dy, dz in coupling.shell_offsets():
            q = (v[0] + dx, v[1] + dy, v[2] + dz)
            o = occ3.get(q)
            if o is None or o == net:
                continue
            key = tuple(sorted([v, q]))
            if key in seen:
                continue
            seen.add(key)
            if coupling.couples(v, q, occ3):
                pairs[(net, o)] += 1
                if v in fixed or q in fixed:
                    struct += 1
                else:
                    free += 1
                details.append((net, v, o, q, v in fixed, q in fixed))
    print(f"shorts: structural(fixed)= {struct}  free= {free}", flush=True)
    print("top net pairs:", flush=True)
    for (a, b), c in pairs.most_common(12):
        print(f"  {a} <-> {b}: {c}", flush=True)
    print("all details (net@pos <-> net@pos [F]=fixed):", flush=True)
    for net, v, o, q, fv, fq in details:
        f = ("F" if fv else ".") + ("F" if fq else ".")
        print(f"  {net}@{v} <-> {o}@{q} [{f}]", flush=True)


if __name__ == "__main__":
    main()
