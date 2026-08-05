"""
solve_iterative.py — STAGE 3: iterate the exact method until no sink is left.

Measured in stage 2b: making ONE net (n32) yield its cells drops alu1 from
6 failed nets / 10 unfed sinks to 2 failed / 3 unfed, with 0 shorts. So the
method works; it just has to be applied repeatedly, because each round exposes a
new (smaller) blocker set.

Loop:
  1. route with the current yield-set
  2. list the unfed sinks
  3. for each, find which nets block EVERY one of its candidates (exact, from the
     real geometry — same rule the router uses)
  4. add the most valuable blocker to the yield-set (the one blocking the most
     sinks) and repeat
Stops when there are no unfed sinks, or when a round adds nothing (then the
placement, not the routing order, is the limit).

This is the "broad first, then narrow" plan: candidates stay fully enumerated,
and the search narrows by *fixing* the order conflicts one at a time.
"""
import sys, os, json, time
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
DUST = "minecraft:redstone_wire"


def route_with_yield(nls, mod, yield_nets, rounds):
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    orig_once = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yield_nets]
        tail = [n for n in nets if n in yield_nets]
        return orig_once(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)
    return res, r, pl


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


def unfed_sinks(res, pl):
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    out = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, ()):
                out.append((n, (k[0], k[2])))
    return out


def blockers_for(net, pin, occ, y0, layers, cell_xz, pin_xz):
    """Which nets block EVERY tower candidate for this sink?"""
    gx, gz = pin
    feed = (gx - 1, gz)
    per_cand = []
    for cy in layers:
        if cy <= y0:
            continue
        for arm, side in ROTS:
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=side, arm=arm)
            if any(c in cell_xz or c in pin_xz for c in foot):
                continue
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            cond.append((feed[0], y0, feed[1]))
            cond.append((feed[0], cy, feed[1]))
            who = set()
            for v in cond:
                o = occ.get(v)
                if o is not None and o != net:
                    who.add(o)
                for dx, dy, dz in SHELL:
                    o = occ.get((v[0]+dx, v[1]+dy, v[2]+dz))
                    if o is not None and o != net:
                        who.add(o)
            per_cand.append(who)
    if not per_cand:
        return None, 0                      # geometrically impossible
    feasible = sum(1 for w in per_cand if not w)
    if feasible:
        return set(), feasible
    common = set.intersection(*per_cand) if per_cand else set()
    if not common:
        # no single net blocks all; return the most frequent blockers
        cnt = Counter()
        for w in per_cand:
            for x in w:
                cnt[x] += 1
        common = {cnt.most_common(1)[0][0]} if cnt else set()
    return common, 0


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    max_iters = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    yield_set = set()
    best = None
    for it in range(max_iters):
        t0 = time.time()
        res, r, pl = route_with_yield(nls, mod, yield_set, rounds)
        sh, _ = r._count_shorts(res)
        uf = unfed_sinks(res, pl)
        y0 = pl.bounds[0][1]
        layers = [y0 + 4 * i for i in range(1, 7)]
        print(f"[iter {it}] yield={sorted(yield_set) or '(none)'} -> "
              f"shorts={sh} failed={len(res.failed)} unfed={len(uf)} "
              f"({time.time()-t0:.0f}s)")
        key = (sh, len(uf))
        if best is None or key < best[0]:
            best = (key, set(yield_set), len(res.failed))
        if not uf:
            print("  ALL SINKS FED")
            break
        occ = conductors(res)
        votes = Counter()
        for net, pin in uf:
            common, feas = blockers_for(net, pin, occ, y0, layers,
                                        r.cell_xz, set(r.pin_net))
            if common is None:
                print(f"   {net}@{pin}: geometrically impossible (no candidate)")
                continue
            if feas:
                print(f"   {net}@{pin}: {feas} candidates feasible — the router "
                      f"just did not find it")
                continue
            print(f"   {net}@{pin}: blocked by {sorted(common)}")
            for b in common:
                votes[b] += 1
        newly = [b for b, _ in votes.most_common() if b not in yield_set]
        if not newly:
            print("  no new blocker to yield — placement/route structure is the limit")
            break
        yield_set.add(newly[0])
        print(f"  -> yielding {newly[0]} next round")
    print(f"\nBEST: shorts={best[0][0]} unfed={best[0][1]} "
          f"failed_nets={best[2]} with yield={sorted(best[1]) or '(none)'}")


if __name__ == "__main__":
    main()
