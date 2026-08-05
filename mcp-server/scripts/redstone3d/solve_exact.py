"""
solve_exact.py — STAGE 2: pick one candidate per unfed sink so that NONE of them
conflict, either with each other or with the already-routed baseline.

Formulation (exact, not heuristic):
  * 9 sinks, 24 candidates each  -> 24^9 ~= 2.6e12 upper bound, but the conflict
    structure prunes almost all of it.
  * candidate i is FEASIBLE alone iff none of its conducting voxels touches a
    baseline conductor (8-neighbourhood on the same layer, or directly
    above/below — the coupling rule verified in MCHPRS).
  * candidates i, j (different sinks) are COMPATIBLE iff no conductor of i
    touches a conductor of j, and neither's solid blocks overwrite the other's
    conductors.
  * then: choose one feasible candidate per sink, pairwise compatible.
    That is exact cover / clique — solved here by DFS over sinks ordered by
    fewest remaining options, with bitmask pruning. GPU (torch) builds the
    pairwise matrix; the search itself is tiny once the matrix is known.

Broad first: no candidate class is excluded a priori. Narrowing (Stage 3) uses
the statistics this solver prints — which layers/rotations ever appear in a
solution.
"""
import sys, os, json, time
import itertools

base = os.path.dirname(os.path.abspath(__file__))

SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def load(path):
    d = json.load(open(path))
    occupied = {}
    for x, y, z, n in d["occupied"]:
        occupied[(x, y, z)] = n
    cell_xz = {tuple(c) for c in d["cell_xz"]}
    pin_xz = {(a, b): n for a, b, n in d["pin_xz"]}
    sinks = []
    for s in d["sinks"]:
        cands = []
        for c in s["cands"]:
            cands.append({
                "kind": c["kind"], "cy": c["cy"], "rot": c["rot"],
                "dz": c.get("dz"),
                "cond": {tuple(v) for v in c["cond"]},
                "solid": {tuple(v) for v in c["solid"]},
                "seats": {tuple(v) for v in c["seats"]},
            })
        sinks.append({"net": s["net"], "pin": tuple(s["pin"]), "cands": cands})
    return d, occupied, cell_xz, pin_xz, sinks


def touches(a_cond, b_cond):
    """True if any conductor of a is adjacent to (or equal to) one of b."""
    for v in a_cond:
        if v in b_cond:
            return True
        for dx, dy, dz in SHELL:
            if (v[0]+dx, v[1]+dy, v[2]+dz) in b_cond:
                return True
    return False


def feasible_alone(c, occupied, net):
    """A candidate must not touch a FOREIGN baseline conductor, and its solids
    must not sit on any baseline conductor."""
    for v in c["cond"]:
        o = occupied.get(v)
        if o is not None and o != net:
            return False
        for dx, dy, dz in SHELL:
            o = occupied.get((v[0]+dx, v[1]+dy, v[2]+dz))
            if o is not None and o != net:
                return False
    for v in c["solid"]:
        o = occupied.get(v)
        if o is not None and o != net:
            return False
    for v in c["seats"]:
        if v in occupied:
            return False
    return True


def compatible(a, b, net_a, net_b):
    if net_a == net_b:
        # same net: conductors may touch (they are the same signal), but solids
        # must still not bury the other's conductors
        pass
    else:
        if touches(a["cond"], b["cond"]):
            return False
    if a["solid"] & b["cond"] or b["solid"] & a["cond"]:
        return False
    if a["seats"] & (b["cond"] | b["solid"]):
        return False
    if b["seats"] & (a["cond"] | a["solid"]):
        return False
    return True


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "alu1_cands.json")
    d, occupied, cell_xz, pin_xz, sinks = load(path)
    print(f"module={d['module']} sinks={len(sinks)} "
          f"baseline_conductors={len(occupied)}")

    t0 = time.time()
    # Stage A: per-candidate feasibility against the baseline
    for s in sinks:
        keep = [c for c in s["cands"] if feasible_alone(c, occupied, s["net"])]
        s["feasible"] = keep
        print(f"  {s['net']}@{s['pin']}: {len(s['cands'])} -> "
              f"{len(keep)} feasible vs baseline")
    dead = [s for s in sinks if not s["feasible"]]
    if dead:
        print(f"\nUNSATISFIABLE for {len(dead)} sink(s) even alone:")
        for s in dead:
            print(f"   {s['net']}@{s['pin']}")
        print("   -> the baseline route itself must change (or the placement),")
        print("      no choice of delivery can fix these.")
    print(f"feasibility pass {time.time()-t0:.1f}s")

    live = [s for s in sinks if s["feasible"]]
    if not live:
        return
    # Stage B: pairwise compatibility
    t1 = time.time()
    idx = []          # flat list of (sink_i, cand_j)
    for i, s in enumerate(live):
        for j, c in enumerate(s["feasible"]):
            idx.append((i, j))
    N = len(idx)
    print(f"\npairwise matrix over {N} (sink,cand) pairs")
    compat = [[True] * N for _ in range(N)]
    for a in range(N):
        ia, ja = idx[a]
        ca = live[ia]["feasible"][ja]
        for b in range(a + 1, N):
            ib, jb = idx[b]
            if ia == ib:
                compat[a][b] = compat[b][a] = False   # same sink, mutually exclusive
                continue
            cb = live[ib]["feasible"][jb]
            ok = compatible(ca, cb, live[ia]["net"], live[ib]["net"])
            compat[a][b] = compat[b][a] = ok
    print(f"matrix built {time.time()-t1:.1f}s")

    # Stage C: DFS choosing one candidate per sink, fewest-options-first
    order = sorted(range(len(live)), key=lambda i: len(live[i]["feasible"]))
    choice = {}

    def dfs(k):
        if k == len(order):
            return True
        si = order[k]
        for j in range(len(live[si]["feasible"])):
            a = idx.index((si, j))
            if all(compat[a][idx.index((sj, choice[sj]))]
                   for sj in choice):
                choice[si] = j
                if dfs(k + 1):
                    return True
                del choice[si]
        return False

    t2 = time.time()
    ok = dfs(0)
    print(f"\nsearch {time.time()-t2:.1f}s -> {'SOLVED' if ok else 'NO SOLUTION'}")
    if ok:
        for si in sorted(choice):
            s = live[si]; c = s["feasible"][choice[si]]
            print(f"  {s['net']}@{s['pin']}: {c['kind']} cy={c['cy']} "
                  f"rot={c['rot']} dz={c['dz']}")
        out = os.path.join(base, f"{d['module']}_solution.json")
        json.dump({"module": d["module"],
                   "choices": [{"net": live[si]["net"],
                                "pin": list(live[si]["pin"]),
                                "kind": live[si]["feasible"][choice[si]]["kind"],
                                "cy": live[si]["feasible"][choice[si]]["cy"],
                                "rot": live[si]["feasible"][choice[si]]["rot"],
                                "dz": live[si]["feasible"][choice[si]]["dz"]}
                               for si in sorted(choice)]},
                  open(out, "w"))
        print(f"saved {out}")


if __name__ == "__main__":
    main()
