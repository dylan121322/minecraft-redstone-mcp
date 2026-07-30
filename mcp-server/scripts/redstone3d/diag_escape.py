"""diag_escape.py — how many nets have a structurally starved SOURCE escape?
A 2-input cell is depth=3: inputs at local z=0 and z=2, output Q at z=1. So the
output pin is sandwiched by its own cell body and can only leave via +x. If that
single +x lane is taken, the net is dead — no amount of negotiation helps (the
failure is structural, not congestion). Count how many sources/sinks are in that
situation, to size a placer/cell fix."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
    pin_xz = {}
    for n, p in pl.net_sources.items():
        pin_xz[(p[0], p[2])] = n
    for n, ks in pl.net_sinks.items():
        for p in ks:
            pin_xz[(p[0], p[2])] = n

    def open_dirs(xz):
        out = []
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (xz[0]+dx, xz[1]+dz)
            if q in cell_xz or q in pin_xz:
                continue
            out.append((dx, dz))
        return out

    starved_src = []
    for n, p in pl.net_sources.items():
        d = open_dirs((p[0], p[2]))
        if len(d) <= 1:
            starved_src.append((n, (p[0], p[2]), d))
    starved_snk = []
    for n, ks in pl.net_sinks.items():
        for p in ks:
            d = open_dirs((p[0], p[2]))
            if len(d) <= 1:
                starved_snk.append((n, (p[0], p[2]), d))
    print(f"[{mod}] nets={len(pl.net_sinks)} cells={len(pl.placed)}")
    print(f"  sources with <=1 escape lane: {len(starved_src)}/{len(pl.net_sources)}")
    for s in starved_src[:10]:
        print(f"    {s}")
    print(f"  sinks with <=1 approach lane: {len(starved_snk)}")
    for s in starved_snk[:10]:
        print(f"    {s}")


if __name__ == "__main__":
    main()
