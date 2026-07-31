"""
rule_mining.py — turn measured failures into new protocol rules.

State: declarations are honest (check_honesty reports 0 mismatches) and the protocol
passes 11/11 chains, yet MCHPRS measures only 3/10 links working. So the rule SET is
incomplete — the protocol checks adjacency, plane, level, repeater pairing and
block-drive, and those five are not enough.

This walks each chain that the protocol accepts, measures it in MCHPRS, and for the
ones that fail, probes the declared port cells one by one to find the first boundary
where the measured power stops matching the declared level. That boundary is the
missing rule, stated in terms of the ports involved rather than as another guess.
"""
from __future__ import annotations
import sys, os, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))

import nucleation as nuc
from placer import place
from route_global_first import route_adaptive
from build_from_route import emit_blocks
from check_chains import chain_for

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def build_world(pl, r, g, zres, nl, drive_net=None, drive=0):
    blocks = {}
    def raw(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    guarded = g.rmap.guarded_setter(raw, writer="local")
    for (_z, _n, rr, _s) in zres:
        emit_blocks(guarded, pl, rr, {n: 0 for n in nl["inputs"]})
    for p, b in g.blocks.items():
        raw(*p, b)

    base_y = pl.bounds[0][1]
    sc = nuc.Schematic.create("mine")
    for (x, y, z), s in blocks.items():
        if "wall_torch" in s and y == base_y:
            continue
        sc.set_block_from_string(x, y, z, s)
    if drive_net:
        src = pl.net_sources[drive_net]
        sc.set_block_from_string(src[0] - 1, base_y, src[2],
                                 RB if drive else "minecraft:air")
        sc.set_block_from_string(src[0], base_y, src[2], W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(90)
    return w, blocks


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)
    base_y = pl.bounds[0][1]

    print(f"[{mod}] walking protocol-approved chains against measurement")
    for net in g.routed:
        for sink in pl.net_sinks[net]:
            c, kind = chain_for(net, pl, r, g, sink)
            if c.validate():
                continue                      # protocol already rejects it
            w1, blocks = build_world(pl, r, g, zres, nl, drive_net=net, drive=1)
            w0, _ = build_world(pl, r, g, zres, nl, drive_net=net, drive=0)
            feed = (sink[0] - 1, base_y, sink[2])
            hi = w1.get_redstone_power(*feed)
            lo = w0.get_redstone_power(*feed)
            if hi > lo:
                print(f"  OK   {c.name} ({kind}) feed {lo}->{hi}")
                continue
            print(f"  FAIL {c.name} ({kind}) feed {lo}->{hi}; walking ports:")
            for seg in c.segments:
                for label, port in (("in", seg.in_port), ("out", seg.out_port)):
                    m1 = w1.get_redstone_power(*port.cell)
                    m0 = w0.get_redstone_power(*port.cell)
                    blk = blocks.get(port.cell, "-").replace("minecraft:", "")[:20]
                    flag = ""
                    if m1 == 0 and port.level > 0:
                        flag = "  <-- declared live, measured dead"
                    elif m1 == m0 and m1 > 0:
                        flag = "  <-- constant, source has no effect"
                    print(f"      {seg.name:13s}.{label:3s} {port.cell} "
                          f"[{blk:20s}] declared={port.level:2d} "
                          f"measured {m0}->{m1}{flag}")
            return                            # one detailed case is enough


if __name__ == "__main__":
    main()
