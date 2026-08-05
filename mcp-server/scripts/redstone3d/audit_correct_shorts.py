"""
audit_correct_shorts.py — audit with the MEASURED coupling rule, which is finer
than either model used so far.

MCHPRS results (test_diag_adjacent.py):
  orthogonal neighbour                              -> couples (12)
  pure diagonal, the other cell isolated            -> does NOT couple (0)
  diagonal WHERE both share an occupied orthogonal cell -> couples (11)
  two lines 1 row apart (that is orthogonal)        -> couples (12)
  two lines 2 rows apart                            -> safe (0)

So the correct predicate for two conductors a, b of DIFFERENT nets:
  * orthogonal (|dx|+|dz| == 1)            -> SHORT
  * directly above/below                   -> SHORT
  * diagonal (|dx| == 1 and |dz| == 1)     -> SHORT **only if** one of the two
    shared orthogonal cells (a.x,b.z) / (b.x,a.z) is itself a conductor
  * anything further                       -> safe

The 8-neighbour model over-reports (rejects legal geometry); the 4-neighbour model
under-reports (misses the shared-cell path). This script measures how many shorts
each model claims versus the correct one, on a real route.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def conductors(res):
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
    return occ


def count(occ, model):
    """model in {'shell8','ortho','correct'}"""
    seen = set()
    for p, net in occ.items():
        x, y, z = p
        for dx, dz in ORTH:
            q = (x+dx, y, z+dz); o = occ.get(q)
            if o is not None and o != net:
                seen.add(tuple(sorted([p, q])))
        for dy in (1, -1):
            q = (x, y+dy, z); o = occ.get(q)
            if o is not None and o != net:
                seen.add(tuple(sorted([p, q])))
        if model == "ortho":
            continue
        for dx, dz in DIAG:
            q = (x+dx, y, z+dz); o = occ.get(q)
            if o is None or o == net:
                continue
            if model == "shell8":
                seen.add(tuple(sorted([p, q])))
            else:  # correct: only via a shared orthogonal conductor
                s1 = (x+dx, y, z)
                s2 = (x, y, z+dz)
                if s1 in occ or s2 in occ:
                    seen.add(tuple(sorted([p, q])))
    return len(seen)


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = (sys.argv[1] if len(sys.argv) > 1 else "alu1,Control").split(",")
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    best = {"alu1": ("n13", "n17", "n7", "n8")}
    print(f"{'module':12s} {'yield':5s} {'shell8':>7s} {'ortho':>6s} "
          f"{'CORRECT':>8s} {'unfed':>6s}")
    for mod in mods:
        for ys in ((), best.get(mod, ())):
            if ys == () and mod in best:
                pass
            pl = place(nls[mod], col_gap=16, row_gap=16)
            r = BuildableRouter(pl, margin=16)
            if ys:
                orig = r._route_once
                yss = set(ys)
                def patched(nets, soft=False, verbose=False, _o=orig, _y=yss):
                    head = [n for n in nets if n not in _y]
                    tail = [n for n in nets if n in _y]
                    return _o(head + tail, soft=soft, verbose=verbose)
                r._route_once = patched
            res = r.route(verbose=False, max_rounds=rounds)
            occ = conductors(res)
            own = {}
            for n in res.wires:
                own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                         {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
            unfed = sum(1 for n in res.failed
                        for k in pl.net_sinks.get(n, [])
                        if (k[0]-1, k[2]) not in own.get(n, ()))
            print(f"{mod:12s} {len(ys):5d} {count(occ,'shell8'):7d} "
                  f"{count(occ,'ortho'):6d} {count(occ,'correct'):8d} "
                  f"{unfed:6d}")
            if not best.get(mod):
                break
    print("\nshell8 - correct = legal geometry the router needlessly rejects")
    print("correct - ortho  = real shorts the 4-neighbour model would miss")


if __name__ == "__main__":
    main()
