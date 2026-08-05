"""diag_pins174.py — are n2's and n17's contested sinks the two INPUTS OF THE
SAME GATE? If so the 2-cell spacing is fixed by cell_library (depth=3, inputs at
local z=0 and z=2), and neither row_gap nor the router can separate them — the
cell geometry itself has to change."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place

nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
col = int(sys.argv[2]) if len(sys.argv) > 2 else 174
pl = place(nls[mod], col_gap=16, row_gap=16)

print(f"[{mod}] gates whose INPUT pins sit at x={col}:")
for name, pc in pl.placed.items():
    if any(p[0] == col for p in pc.input_pins.values()):
        print(f"  {name} ({pc.gtype}) origin={pc.origin}")
        for pin, p in sorted(pc.input_pins.items()):
            # which net drives this pin?
            drv = None
            for net, sinks in pl.net_sinks.items():
                if p in sinks:
                    drv = net; break
            print(f"     input {pin} @ {p}  driven by {drv}")
        for pin, p in sorted(pc.output_pins.items()):
            drv = None
            for net, s in pl.net_sources.items():
                if (s[0]-1, s[1], s[2]) == p or s == p:
                    drv = net; break
            print(f"     output {pin} @ {p}  net {drv}")

print(f"\ncell depth/pin spacing from cell_library:")
import cell_library as clib
for t in ("AND", "OR", "NAND", "NOR", "NOT"):
    c = clib.get(t)
    print(f"  {t}: width={c.width} depth={c.depth} inputs={c.inputs} "
          f"outputs={c.outputs}")
print("\n=> if the two contested pins belong to ONE gate, their z-distance is")
print("   fixed at 2 by the cell layout: row_gap cannot change it, and two")
print("   different nets must then share the single row between them.")
