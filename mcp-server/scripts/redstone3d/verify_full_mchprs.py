"""
verify_full_mchprs.py — build the FULL alu1 routed geometry in MCHPRS and check
its truth table. Per vector: rebuild schematic, inject PI redstone_blocks, tick,
read PO power. This is the whole-chip physical confirmation.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc

RB = "minecraft:redstone_block"

def main():
    fj = os.environ.get("FULL_JSON", r"E:\project\alu1_full.json")
    d = json.load(open(fj))
    blocks = d["blocks"]; pi = d["pi_inject"]; po = d["po_read"]
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pb = nl["port_bits"]
    def nm(b): return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]; y_n, cout_n = nm(pb["y"][0]), nm(pb["cout"][0])

    def run(a, b, cin, op):
        sc = nuc.Schematic.create("full")
        for x, y, z, s in blocks:
            sc.set_block_from_string(x, y, z, s)
        iv = {a_n: a, b_n: b, cin_n: cin}
        for i in range(4): iv[op_n[i]] = (op >> i) & 1
        # inject PIs
        for net, p in pi.items():
            sc.set_block_from_string(p[0], p[1], p[2],
                                     RB if iv.get(net, 0) else "minecraft:air")
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(40)
        yv = 1 if w.get_redstone_power(*po[y_n]) > 0 else 0
        cv = 1 if w.get_redstone_power(*po[cout_n]) > 0 else 0
        return yv, cv

    tests = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for b in (0, 1):
                for cin in (0, 1):
                    tests.append((a, b, cin, op))
    # optionally limit for speed
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(tests)
    ok = 0; total = 0
    t0 = time.time()
    for (a, b, cin, op) in tests[:limit]:
        yv, cv = run(a, b, cin, op)
        bb = (1-b) if op == 6 else b
        summ = a ^ bb ^ cin; cout = (a & bb) | (cin & (a ^ bb))
        ey = {0: a&b, 1: a|b, 2: summ, 3: a^b, 6: summ}.get(op, 0)
        good = (yv == ey and cv == cout)
        ok += good; total += 1
        print(f"  op={op} a={a} b={b} cin={cin}: y={yv}(e{ey}) cout={cv}(e{cout}) "
              f"{'OK' if good else 'X'}", flush=True)
    print(f"FULL alu1 MCHPRS: {ok}/{total}  ({time.time()-t0:.1f}s)")

if __name__ == "__main__":
    main()
