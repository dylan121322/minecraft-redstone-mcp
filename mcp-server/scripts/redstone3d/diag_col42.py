"""
diag_col42.py — the unfed sinks cluster on specific COLUMNS, not randomly:

    x=42  : n25(42,2) n25(42,21) n5(42,19) n6(42,38) n28(42,57)   <- five!
    x=120 : n14(120,2)
    x=174 : n17(174,2)

Five different nets fail at x=42 across different yield-sets, so something about
that column's geometry blocks delivery. Print what sits at x=41/42/43 (the feed
column, the pin column and beyond) for the whole z range: which gates are there,
where their pins are, and how much free space the feed cells have.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    col = int(sys.argv[2]) if len(sys.argv) > 2 else 42
    pl = place(nls[mod], col_gap=16, row_gap=16)
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
    pin_of = {}
    for n, p in pl.net_sources.items():
        pin_of[(p[0], p[2])] = ("SRC", n)
    for n, ks in pl.net_sinks.items():
        for p in ks:
            pin_of[(p[0], p[2])] = ("SINK", n)

    print(f"[{mod}] gates with pins at x={col}:")
    for name, pc in sorted(pl.placed.items(), key=lambda kv: kv[1].origin[2]):
        pins = list(pc.input_pins.values()) + list(pc.output_pins.values())
        if any(p[0] == col for p in pins):
            print(f"  {name} ({pc.gtype}) origin={pc.origin} "
                  f"in={pc.input_pins} out={pc.output_pins}")

    print(f"\ncolumn map x={col-2}..{col+2} (C=cell body, S=sink pin, "
          f"s=source pin, .=free):")
    zs = sorted({p[2] for p in pl.occupancy})
    zmin, zmax = min(zs), max(zs)
    for z in range(zmin - 1, zmax + 2):
        row = []
        for x in range(col - 2, col + 3):
            c = (x, z)
            if c in pin_of:
                kind, n = pin_of[c]
                row.append(f"{'S' if kind=='SINK' else 's'}{n[1:]:>3s}")
            elif c in cell_xz:
                row.append("   C")
            else:
                row.append("   .")
        line = " ".join(row)
        if line.strip(". "):
            print(f"  z={z:3d}: {line}")

    print(f"\nfeed-cell room for each sink at x={col} "
          f"(free cells in the 4 orthogonal directions):")
    for n, ks in sorted(pl.net_sinks.items()):
        for k in ks:
            if k[0] != col:
                continue
            feed = (col - 1, k[2])
            free = []
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                q = (feed[0] + dx, feed[1] + dz)
                if q not in cell_xz and q not in pin_of:
                    free.append((dx, dz))
            print(f"  {n:5s} sink{(k[0], k[2])} feed{feed}: "
                  f"free dirs={free} "
                  f"{'(feed itself is a pin!)' if feed in pin_of else ''}")


if __name__ == "__main__":
    main()
