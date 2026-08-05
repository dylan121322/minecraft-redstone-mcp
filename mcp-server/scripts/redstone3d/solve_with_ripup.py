"""
solve_with_ripup.py — STAGE 2b: the exact solver proved three sinks unsatisfiable
against the CURRENT baseline, and diag_unsat named the exact blockers:

    n18@(252,0)   <- n21 kills all 24 candidates
    n2@(18,19)    <- n3  kills all 24 candidates
    n2@(174,0)    <- n17 kills 18, n32 kills 6 (no single common blocker)

So the search space must include RIPPING UP a small set of blockers and letting
them reroute. This file measures the cost/benefit of each rip-up choice exactly:
for every candidate blocker set, it re-runs the router with those nets forced to
route LAST (i.e. they yield their cells to everyone else) and reports how many
sinks become feasible.

This keeps the enumeration honest: we do not guess that "ripping n21 helps", we
measure it. Broad first — try every single blocker and the obvious pairs.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
import route_buildable as RB
from route_buildable import BuildableRouter


def route_with_yield(nls, mod, yield_nets, rounds=6):
    """Route with `yield_nets` pushed to the END of the order, so every other net
    claims its cells first. Returns (res, router, placement)."""
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    orig = r.route

    # monkey-patch the ordering: easiest reliable hook is to wrap _route_once and
    # reorder the net list it receives.
    orig_once = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yield_nets]
        tail = [n for n in nets if n in yield_nets]
        return orig_once(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)
    return res, r, pl


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


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6

    trials = [
        (),                       # baseline
        ("n21",),
        ("n3",),
        ("n32",),
        ("n17",),
        ("n21", "n3"),
        ("n21", "n3", "n32"),
        ("n21", "n3", "n17"),
        ("n21", "n3", "n32", "n17"),
    ]
    print(f"[{mod}] measuring rip-up (yield-last) options, {rounds} rounds each")
    results = []
    for ys in trials:
        t0 = time.time()
        res, r, pl = route_with_yield(nls, mod, set(ys), rounds)
        sh, _ = r._count_shorts(res)
        uf = unfed_sinks(res, pl)
        results.append((ys, sh, len(res.failed), len(uf), time.time()-t0))
        print(f"  yield={ys or '(none)'}: shorts={sh} failed_nets={len(res.failed)} "
              f"unfed_sinks={len(uf)} ({time.time()-t0:.0f}s)")
        if uf:
            print(f"     still unfed: {[(n, p) for n, p in uf][:8]}")
    print("\n=== summary (fewest unfed sinks wins, shorts must be 0) ===")
    for ys, sh, fn, uf, secs in sorted(results, key=lambda t: (t[1], t[3])):
        label = ",".join(ys) if ys else "(none)"
        print(f"  yield={label:28s} shorts={sh} failed={fn} unfed={uf}")


if __name__ == "__main__":
    main()
