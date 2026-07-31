"""
check_chains.py — run the signal protocol over every global net of a module.

This is the payoff of signal_protocol: instead of building a world, measuring a
lamp and guessing which of five hand-joined segments broke, each segment declares
its ports and the boundaries are checked arithmetically. A decayed hand-off, a
plane mismatch or an unwanted inversion is named at once.

The declared decay figures come from measurements already taken (staircase loses
one level per level dropped, refreshed runs re-drive to 15, torch towers regenerate
but invert per torch), so a violation here corresponds to a real failure.
"""
from __future__ import annotations
import sys, os, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))

from placer import place
from route_global_first import route_adaptive
from delivery_box import delivery_for_sink
from signal_protocol import (Chain, Polarity, seg_up_tower, seg_trunk, seg_leg,
                             seg_stairs_box, seg_tower_box, seg_feed_run, seg_pin)


def chain_for(net, pl, r, g, sink):
    """Describe one global net's path to one sink as protocol segments."""
    ty = r.net_trunk_y[net]
    row = g.trunk_rows[net]
    src = pl.net_sources[net]
    base = r.base_y
    sx, sz = src[0], src[2]
    tower_x = sx + 2                       # the router's climb column
    torches = (ty - 1 - base) // 2

    box, kind = delivery_for_sink((sink[0], sink[2]), ty, base, gap=2)
    ix, iy, iz = box.in_cell
    ox, oy, oz = box.out_cell

    c = Chain(f"{net}->({sink[0]},{sink[2]})")
    c.add(seg_up_tower((tower_x, base, sz), ty, torches))
    c.add(seg_trunk((tower_x, ty, sz), (tower_x, ty, row), ty))
    c.add(seg_leg((tower_x, ty, row), (ix, ty, row), ty))
    c.add(seg_leg((ix, ty, row), (ix, iy, iz), ty))
    # describe the delivery as what it ACTUALLY is: a staircase decays with depth,
    # a tower does not but inverts unless its internal inverter is wired. Declaring
    # this honestly is what lets the protocol reject a bad composition.
    if kind == "stairs":
        c.add(seg_stairs_box(box.in_cell, box.out_cell, box.drop))
    else:
        # measured non-inverting after removing the (unnecessary) inverter:
        # test_two_boxes shows drop 4..28 all delivering with drive0 == 0
        c.add(seg_tower_box(box.in_cell, box.out_cell, box.drop,
                            inverter_inside=True))
    c.add(seg_feed_run(box.out_cell, (sink[0] - 1, base, oz)))
    c.add(seg_pin((sink[0] - 1, base, oz), (sink[0], base, sink[2])))
    return c, kind


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    verbose = "-v" in sys.argv
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)
    print(f"[{mod}] {len(g.routed)} global nets routed; checking their chains")

    total = ok = 0
    reasons = {}
    for net in g.routed:
        for sink in pl.net_sinks[net]:
            c, kind = chain_for(net, pl, r, g, sink)
            viol = c.validate(Polarity.NORMAL)
            total += 1
            if not viol:
                ok += 1
                if verbose:
                    print(f"  OK   {c.name} ({kind})")
                continue
            if verbose:
                print(f"  FAIL {c.name} ({kind})")
                for v in viol:
                    print(f"         {v}")
            for v in viol:
                key = v.reason.split(":")[0].split("(")[0].strip()
                reasons[key] = reasons.get(key, 0) + 1
    print(f"  chains passing the protocol: {ok}/{total}")
    if reasons:
        print("  violation kinds:")
        for k, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {n:3d}x  {k}")


if __name__ == "__main__":
    main()
