"""
test_zone_route.py — validate the central assumption of PARTITION_PLAN before
building the full flow: does routing a zone's nets ALONE beat routing everything
globally?

Method: for each zone, run the existing router on the SAME placement but with only
that zone's local nets, and compare the routed fraction against the global run.
Global nets are excluded here (they are P3's job); the question is purely whether
reduced competition raises the local success rate.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from partition import Planner


def route_subset(pl, nets, rounds=2, margin=16):
    """Route only `nets` on this placement. The router walks pl.net_sinks, so we
    hand it a shallow view restricted to the subset."""
    import copy
    sub = copy.copy(pl)
    sub.net_sinks = {n: pl.net_sinks[n] for n in nets}
    sub.net_sources = {n: pl.net_sources[n] for n in nets
                       if pl.net_sources.get(n)}
    r = BuildableRouter(sub, margin=margin)
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    return len(nets) - len(res.failed), shorts, res.total_wires(), res.failed


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or ["alu1"]
    W = next((int(a) for a in sys.argv[1:] if a.isdigit()), 64)
    for mod in mods:
        nl = nls[mod]
        pl = place(nl, col_gap=16, row_gap=16)
        plan = Planner(pl, zone_width=W).plan()

        allnets = [n for n in pl.net_sinks
                   if pl.net_sources.get(n) and pl.net_sinks.get(n)]
        t0 = time.time()
        g_ok, g_sh, g_wire, g_failed = route_subset(pl, allnets)
        g_secs = time.time() - t0

        # zone-by-zone on local nets only
        by_zone = {}
        for n in plan.local_nets:
            z = next(iter(plan.net_zones[n]))
            by_zone.setdefault(z, []).append(n)

        z_ok = z_sh = z_wire = 0
        t1 = time.time()
        details = []
        for z, nets in sorted(by_zone.items()):
            ok, sh, wire, failed = route_subset(pl, nets)
            z_ok += ok; z_sh += sh; z_wire += wire
            details.append((z, len(nets), ok, sh))
        z_secs = time.time() - t1

        loc = len(plan.local_nets)
        # how did those same local nets fare inside the global run?
        g_loc_ok = sum(1 for n in plan.local_nets if n not in g_failed)
        print(f"[{mod} W={W}] nets={len(allnets)} local={loc} "
              f"global={len(plan.global_nets)}")
        print(f"  global run : routed {g_ok}/{len(allnets)} shorts={g_sh} "
              f"wires={g_wire} {g_secs:.0f}s"
              f"   (local nets inside it: {g_loc_ok}/{loc})")
        print(f"  zone runs  : routed {z_ok}/{loc} shorts={z_sh} "
              f"wires={z_wire} {z_secs:.0f}s")
        print(f"  per zone   : {details}")
        gain = z_ok - g_loc_ok
        print(f"  => local routed {'+' if gain >= 0 else ''}{gain} "
              f"({g_loc_ok} -> {z_ok}), shorts {g_sh} -> {z_sh}")


if __name__ == "__main__":
    main()
