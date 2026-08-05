"""inspect_cands.py — sanity-check the enumerated candidate dump before writing
the GPU solver: what kinds survived, which cross layers, and whether a
candidate's voxel sets look right."""
import json, sys, os
from collections import Counter

base = os.path.dirname(os.path.abspath(__file__))
f = sys.argv[1] if len(sys.argv) > 1 else os.path.join(base, "alu1_cands.json")
d = json.load(open(f))
print(f"module={d['module']} y0={d['y0']} layers={d['layers']}")
print(f"baseline occupied conducting voxels: {len(d['occupied'])}")
print(f"cell_xz={len(d['cell_xz'])} pins={len(d['pin_xz'])}")
print(f"sinks={len(d['sinks'])}")
allk = Counter(); allcy = Counter(); allrot = Counter()
for s in d["sinks"]:
    for c in s["cands"]:
        allk[c["kind"]] += 1
        allcy[c["cy"]] += 1
        allrot[str(c["rot"])] += 1
print(f"\nacross all sinks: kinds={dict(allk)}")
print(f"cross-layer distribution={dict(sorted(allcy.items()))}")
print(f"rotations={dict(allrot)}")
s = d["sinks"][0]
print(f"\nexample sink {s['net']}@{s['pin']} — {len(s['cands'])} candidates")
for c in s["cands"][:3]:
    print(f"  kind={c['kind']} cy={c['cy']} rot={c['rot']} "
          f"cond={len(c['cond'])} solid={len(c['solid'])} seats={len(c['seats'])}")
    ys = sorted({v[1] for v in c["cond"]})
    xs = sorted({v[0] for v in c["cond"]})
    zs = sorted({v[2] for v in c["cond"]})
    print(f"     cond y-range={ys[0]}..{ys[-1]} x-span={xs[-1]-xs[0]+1} "
          f"z-span={zs[-1]-zs[0]+1}")
print("\nnote: 150 raw -> 24 viable means all 17 staircase offsets were rejected")
print("      (they hit gate bodies/pins) and only the 4 usable tower rotations")
print("      survive on each of the 6 cross layers: 6*4 = 24.")
