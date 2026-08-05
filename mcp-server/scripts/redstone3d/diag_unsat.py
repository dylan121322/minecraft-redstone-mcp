"""
diag_unsat.py — for the sinks the exact solver proved UNSATISFIABLE, report WHO
blocks every one of their 24 candidates. That is the actionable output: if one or
two nets are responsible, ripping just those up (or nudging the placement) is
enough; if the blockers are spread out, the placement itself must change.
"""
import sys, os, json
from collections import Counter

base = os.path.dirname(os.path.abspath(__file__))
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "alu1_cands.json")
    d = json.load(open(path))
    occupied = {}
    for x, y, z, n in d["occupied"]:
        occupied[(x, y, z)] = n

    for s in d["sinks"]:
        net = s["net"]
        blockers = Counter()
        cand_blockers = []
        n_feasible = 0
        for c in s["cands"]:
            who = set()
            for v in c["cond"]:
                vv = tuple(v)
                o = occupied.get(vv)
                if o is not None and o != net:
                    who.add(o)
                for dx, dy, dz in SHELL:
                    o = occupied.get((vv[0]+dx, vv[1]+dy, vv[2]+dz))
                    if o is not None and o != net:
                        who.add(o)
            for v in c["solid"]:
                o = occupied.get(tuple(v))
                if o is not None and o != net:
                    who.add(o)
            if not who:
                n_feasible += 1
            else:
                for w in who:
                    blockers[w] += 1
                cand_blockers.append((c["cy"], c["rot"], sorted(who)))
        status = "OK" if n_feasible else "UNSAT"
        print(f"{net}@{tuple(s['pin'])}: {n_feasible}/{len(s['cands'])} feasible [{status}]")
        if not n_feasible:
            print(f"   blockers (net -> how many candidates it kills): "
                  f"{dict(blockers.most_common(8))}")
            # the minimal set: which nets appear in EVERY candidate's blocker set?
            common = None
            for _cy, _rot, who in cand_blockers:
                s2 = set(who)
                common = s2 if common is None else (common & s2)
            print(f"   present in EVERY candidate: {sorted(common) if common else '(none)'}")
            print(f"   -> ripping up {sorted(common) if common else 'a spread of nets'} "
                  f"is the only way to open this sink")


if __name__ == "__main__":
    main()
