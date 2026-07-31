"""
diag_placement.py — why are connections so long? Measure the placement itself:
column shape, how far apart connected gates end up, and how much of the total
wire length comes from a few cross-field nets. This tells us what a reordering
pass has to optimise.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from collections import defaultdict


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    mn, mx = pl.bounds
    print(f"[{mod}] gates={len(nl['cells'])} bbox x={mx[0]-mn[0]+1} z={mx[2]-mn[2]+1}")

    # columns: group placed cells by x origin
    cols = defaultdict(list)
    for name, pc in pl.placed.items():
        cols[pc.origin[0]].append((pc.origin[2], name))
    print(f"columns={len(cols)}  cells per column: "
          f"{[len(v) for _, v in sorted(cols.items())]}")

    # connection lengths, and how much each contributes
    lens = []
    for n, ks in pl.net_sinks.items():
        s = pl.net_sources.get(n)
        if not s:
            continue
        for k in ks:
            d = abs(s[0]-k[0]) + abs(s[2]-k[2])
            lens.append((d, n, (s[0], s[2]), (k[0], k[2])))
    lens.sort(reverse=True)
    total = sum(d for d, *_ in lens)
    print(f"connections={len(lens)} total_manhattan={total}")
    top = lens[:8]
    share = sum(d for d, *_ in top) / total * 100 if total else 0
    print(f"top-8 longest account for {share:.0f}% of total length:")
    for d, n, a, b in top:
        print(f"   {n:5s} {d:4d}  {a} -> {b}")

    # z-span per net: does a net span many rows (which forces long z travel)?
    zspan = []
    for n, ks in pl.net_sinks.items():
        s = pl.net_sources.get(n)
        if not s:
            continue
        zs = [s[2]] + [k[2] for k in ks]
        zspan.append((max(zs) - min(zs), n))
    zspan.sort(reverse=True)
    print(f"largest z-spans: {[(z, n) for z, n in zspan[:6]]}")

    # how many gates does each net touch (fanout)?
    fo = sorted(((len(ks), n) for n, ks in pl.net_sinks.items()), reverse=True)
    print(f"highest fanout nets: {fo[:6]}")


if __name__ == "__main__":
    main()
