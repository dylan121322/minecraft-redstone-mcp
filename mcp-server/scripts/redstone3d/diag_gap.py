"""
diag_gap.py — why do the remaining nets still fail under the global-first flow?

Two gaps are left: Forwarding routes only 54/84 local nets, and ALU/Forwarding
keep a handful of shorts. This attributes each failure to a concrete cause rather
than guessing:

  * zone load     — how many local nets share each zone (competition)
  * corridor bite — how much y0 ground the global trunks reserved inside a zone
  * pin room      — whether the failing nets' sinks still had a free west feed
  * span          — whether failures are simply the longest local nets
"""
import sys, os, json, copy
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from route_global_first import GlobalFirstRouter


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "Forwarding"
    zw = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = GlobalFirstRouter(pl, zone_width=zw)
    nets, local, glob = r.classify()
    g = r.build_globals(glob)
    print(f"[{mod}] nets={len(nets)} local={len(local)} global={len(glob)} "
          f"global_routed={len(g.routed)} reserved_cols={len(g.reserved)}")

    # zone load and how much the trunks reserved per zone
    by_zone = {}
    for n in local:
        by_zone.setdefault(r._zone(pl.net_sources[n][0]), []).append(n)
    res_by_zone = Counter(r._zone(x) for (x, _z) in g.reserved)
    print(f"  local nets per zone : "
          f"{ {z: len(v) for z, v in sorted(by_zone.items())} }")
    print(f"  reserved cols/zone  : {dict(sorted(res_by_zone.items()))}")

    # route each zone and inspect the failures
    total_fail = []
    for z, nets_z in sorted(by_zone.items()):
        sub = copy.copy(pl)
        sub.net_sinks = {n: pl.net_sinks[n] for n in nets_z}
        sub.net_sources = {n: pl.net_sources[n] for n in nets_z}
        sub.occupancy = set(pl.occupancy) | \
            {(x, r.base_y, zz) for (x, zz) in g.reserved}
        rr = BuildableRouter(sub, margin=16)
        out = rr.route(verbose=False, max_rounds=2)
        sh, _ = rr._count_shorts(out)
        print(f"  zone {z}: {len(nets_z)} nets -> routed "
              f"{len(nets_z)-len(out.failed)} shorts={sh} failed={out.failed[:6]}")
        for n in out.failed:
            s = pl.net_sources[n]
            spans = [abs(s[0]-k[0]) + abs(s[2]-k[2]) for k in pl.net_sinks[n]]
            # was every sink's feed cell still free of foreign wiring?
            blocked = []
            for k in pl.net_sinks[n]:
                feed = (k[0]-1, k[2])
                why = []
                if feed in rr.cell_xz:
                    why.append("cell")
                if feed in rr.pin_net and rr.pin_net[feed] != n:
                    why.append(f"pin:{rr.pin_net[feed]}")
                if feed in g.reserved:
                    why.append("trunk-reserved")
                if why:
                    blocked.append((feed, why))
            total_fail.append({"net": n, "zone": z, "sinks": len(spans),
                               "max_span": max(spans), "blocked": blocked[:3]})

    print(f"\n  failures ({len(total_fail)}):")
    span_hist = Counter()
    cause = Counter()
    for f in total_fail:
        span_hist[f["max_span"] // 50 * 50] += 1
        if f["blocked"]:
            cause["feed blocked: " + ",".join(w for _c, ws in f["blocked"] for w in ws)] += 1
        else:
            cause["feed free (planar routing gave up)"] += 1
    for f in total_fail[:10]:
        print(f"    {f['net']:5s} zone={f['zone']} sinks={f['sinks']} "
              f"max_span={f['max_span']} blocked={f['blocked']}")
    print(f"  span buckets (max_span//50): {dict(sorted(span_hist.items()))}")
    print(f"  causes: {dict(cause)}")


if __name__ == "__main__":
    main()
