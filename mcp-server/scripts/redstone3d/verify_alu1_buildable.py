"""
verify_alu1_buildable.py — run the C-plan (BuildableRouter: y0 shortest-path +
y2 bridges) on alu1 and check its truth table in MCHPRS. Baseline before we
swap the bridge climb/descent for the verified 1x1 torch tower.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_buildable import verify

base = os.path.dirname(os.path.abspath(__file__))
nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
nl = nls["alu1"]
pb = nl["port_bits"]

def nm(b):
    return f"n{b}" if not isinstance(b, str) else f"const_{b}"

a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
op_n = [nm(x) for x in pb["op"]]
y_n, cout_n = nm(pb["y"][0]), nm(pb["cout"][0])

def spec(iv):
    a = iv[a_n]; b = iv[b_n]; cin = iv[cin_n]
    op = sum((iv[op_n[i]] & 1) << i for i in range(4))
    bb = (1 - b) if op == 6 else b
    summ = a ^ bb ^ cin
    cout = (a & bb) | (cin & (a ^ bb))
    y = {0: a & b, 1: a | b, 2: summ, 3: a ^ b, 6: summ}.get(op, 0)
    return {y_n: y, cout_n: cout}

tvs = []
for op in (0, 1, 2, 3, 6):
    for a in (0, 1):
        for b in (0, 1):
            for cin in (0, 1):
                iv = {a_n: a, b_n: b, cin_n: cin}
                for i in range(4):
                    iv[op_n[i]] = (op >> i) & 1
                for inet in nl["inputs"]:
                    iv.setdefault(inet, 0)
                tvs.append(iv)

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(tvs)
    verify(nl, spec, tvs[:limit], col_gap=16, row_gap=16, ticks=40,
           verbose=True, name="alu1")
