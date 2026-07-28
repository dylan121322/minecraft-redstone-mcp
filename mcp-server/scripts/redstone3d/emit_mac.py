"""
emit_mac.py — Mac-side emit driver: take a pre-computed even-layer route JSON
(from Win GPU) + re-derive the matching placement, build full geometry, and save
a blocks JSON for MCHPRS verification. No routing here (that's Win's job).
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from emit_full import build_full

def main(route_json, mod, out_json):
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    data = json.load(open(route_json))
    # placement MUST match the routing run (same gaps)
    pl = place(nls[mod], col_gap=16, row_gap=16)
    blocks, pi, po = build_full(data, nls[mod], pl)
    xs = [k[0] for k in blocks]; ys = [k[1] for k in blocks]; zs = [k[2] for k in blocks]
    print(f"[{mod}] FULL: {len(blocks)} blocks  bbox "
          f"x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}] z[{min(zs)},{max(zs)}]")
    print(f"  PI={len(pi)} PO={len(po)}")
    out = {"blocks": [[x, y, z, s] for (x, y, z), s in blocks.items()],
           "pi_inject": pi, "po_read": po, "module": mod}
    json.dump(out, open(out_json, "w"))
    print(f"  saved {out_json}")

if __name__ == "__main__":
    rj = sys.argv[1] if len(sys.argv) > 1 else "/tmp/alu1_even.json"
    mod = sys.argv[2] if len(sys.argv) > 2 else "alu1"
    oj = sys.argv[3] if len(sys.argv) > 3 else "/tmp/alu1_full.json"
    main(rj, mod, oj)
