"""
verify_module_mchprs.py — route a real RISC-V module with BuildableRouter and
verify its truth table in MCHPRS (L1). The gate before any in-game build.

Usage: python3 verify_module_mchprs.py <module> [col_gap row_gap max_iters]
"""
import sys, os, time
from collections import Counter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
from yosys_frontend import compile_verilog
from verify_buildable import verify

MODS = {
    "alu1": ("alu1.v", "alu1"),
    "Control": ("Control.v", "Control"),
    "ALU_Control": ("ALU_Control.v", "ALU_Control"),
    "Mux_2to1": ("Mux_2to1.v", "Mux_2to1"),
    "Imm_Gen": ("Imm_Gen.v", "Imm_Gen"),
}


def netname(bit):
    return f"n{bit}" if not isinstance(bit, str) else f"const_{bit}"


def build_alu1(nl):
    pb = nl["port_bits"]
    a_n, b_n, cin_n = netname(pb["a"][0]), netname(pb["b"][0]), netname(pb["cin"][0])
    op_n = [netname(x) for x in pb["op"]]
    y_n, cout_n = netname(pb["y"][0]), netname(pb["cout"][0])

    tvs = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for b in (0, 1):
                for cin in (0, 1):
                    iv = {a_n: a, b_n: b, cin_n: cin}
                    for i in range(4):
                        iv[op_n[i]] = (op >> i) & 1
                    iv["_a"], iv["_b"], iv["_cin"], iv["_op"] = a, b, cin, op
                    tvs.append(iv)

    def spec(iv):
        a, b, cin, op = iv["_a"], iv["_b"], iv["_cin"], iv["_op"]
        bb = (1 - b) if op == 6 else b
        summ = a ^ bb ^ cin
        cout = (a & bb) | (cin & (a ^ bb))
        y = {0: a & b, 1: a | b, 2: summ, 3: a ^ b, 6: summ}.get(op, 0)
        return {y_n: y, cout_n: cout}

    # strip the _-prefixed helper keys before feeding to the router/sim inputs
    clean = []
    for iv in tvs:
        clean.append({k: v for k, v in iv.items() if not k.startswith("_")})
    # but spec needs the helpers; wrap:
    specs = []
    for iv in tvs:
        specs.append(spec(iv))
    return clean, specs


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    col_gap = int(sys.argv[2]) if len(sys.argv) > 2 else 16
    row_gap = int(sys.argv[3]) if len(sys.argv) > 3 else 10
    max_iters = int(sys.argv[4]) if len(sys.argv) > 4 else 150

    vfile, top = MODS[mod]
    nl = compile_verilog(os.path.join(HERE, "..", "riscv_synth", vfile), top=top)
    print(f"{mod}: {len(nl['cells'])} gates {dict(Counter(c['type'] for c in nl['cells'].values()))}")

    if mod == "alu1":
        tvs, specs = build_alu1(nl)
        # verify() takes spec as a callable; precompute a dict keyed by index
        spec_iter = iter(specs)
        spec_map = {id(tv): sp for tv, sp in zip(tvs, specs)}
        def spec_fn(iv):
            return spec_map[id(iv)]
        t0 = time.time()
        ok, res, pl = verify(nl, spec_fn, tvs, col_gap=col_gap, row_gap=row_gap,
                             name=mod, verbose=True, ticks=24)
        print(f"{mod}: {'PASS' if ok else 'FAIL'} in {time.time()-t0:.1f}s")
    else:
        print("only alu1 wired up in this harness so far")
