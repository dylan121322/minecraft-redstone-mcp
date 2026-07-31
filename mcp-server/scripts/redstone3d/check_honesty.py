"""
check_honesty.py — does each protocol declaration match the geometry actually
emitted?

The protocol reports 11/11 chains valid while MCHPRS measures 3/10 links working.
A protocol can only be as good as the honesty of its declarations, so the
discrepancy means some segment describes a cell that the router does not really
emit (or emits as something else). This tool takes every declared Port, looks the
cell up in the built block set, and reports the mismatches — turning "the protocol
lied" into a specific list of wrong declarations.
"""
from __future__ import annotations
import sys, os, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))

from placer import place
from route_global_first import route_adaptive
from build_from_route import emit_blocks
from signal_protocol import Kind
from check_chains import chain_for

EXPECT = {
    Kind.DUST: ("redstone_wire", "repeater"),      # a refreshed run may end on one
    Kind.REPEATER_OUT: ("repeater",),
    Kind.TORCH_OUT: ("torch",),
    Kind.BLOCK: ("stone",),
}


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)

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

    print(f"[{mod}] auditing protocol declarations against emitted geometry")
    bad = 0
    for net in g.routed:
        for sink in pl.net_sinks[net]:
            c, kind = chain_for(net, pl, r, g, sink)
            issues = []
            for seg in c.segments:
                for label, port in (("in", seg.in_port), ("out", seg.out_port)):
                    got = blocks.get(port.cell)
                    if got is None:
                        issues.append(f"{seg.name}.{label} {port.cell} is EMPTY "
                                      f"(declared {port.kind.value})")
                        continue
                    want = EXPECT[port.kind]
                    if not any(t in got for t in want):
                        issues.append(f"{seg.name}.{label} {port.cell} holds "
                                      f"{got.replace('minecraft:', '')} but was "
                                      f"declared {port.kind.value}")
            if issues:
                bad += 1
                print(f"  {c.name} ({kind}): {len(issues)} mismatch(es)")
                for i in issues[:5]:
                    print(f"      {i}")
    print(f"  chains whose declarations do not match reality: {bad}")


if __name__ == "__main__":
    main()
