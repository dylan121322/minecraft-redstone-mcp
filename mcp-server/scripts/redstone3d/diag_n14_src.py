"""diag_n14_src.py — n14 has ZERO wires. Check its source: is the published
source inside another cell's occupancy, or off-grid, so the y0 BFS never even
starts?"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place

nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
pl = place(nls["alu1"], col_gap=16, row_gap=16)
s = pl.net_sources["n14"]
print("n14 source:", s)
for st in pl.out_stubs:
    if tuple(st[1]) == tuple(s):
        print("  out_stub: real_pin", st[0], "-> published", st[1])
for name, pc in pl.placed.items():
    if pc.origin[0] <= s[0] <= pc.origin[0] + 10 and \
       pc.origin[2] - 1 <= s[2] <= pc.origin[2] + 3:
        print("  gate near source:", name, pc.gtype, "origin", pc.origin)
occ = {(p[0], p[2]) for p in pl.occupancy}
print("cell occupancy within 4 of source:")
for dz in range(-4, 5):
    row = []
    for dx in range(-4, 5):
        q = (s[0] + dx, s[2] + dz)
        row.append("C" if q in occ else ".")
    print(f"  dz={dz:+d}: " + " ".join(row))
# is the source itself on a cell?
print("source on cell?", (s[0], s[2]) in occ)
# all 24 gates' origins for reference
print("\ngate origins (x,z):")
for name, pc in sorted(pl.placed.items(), key=lambda kv: kv[1].origin[0]):
    print(f"  {name:10s} ({pc.origin[0]:4d},{pc.origin[2]:4d}) {pc.gtype}")
