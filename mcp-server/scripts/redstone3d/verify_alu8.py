"""Hierarchical verification of the yosys-synthesized 8-bit ALU (160 gates)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from yosys_frontend import compile_verilog
from regress import eval_netlist, verify_physical

nl = compile_verilog("_alu8.v")
pb = nl["port_bits"]

def bus_nets(port):
    """net names for each bit of a bus port, LSB first."""
    return [f"n{b}" if not isinstance(b, str) else f"const_{b}" for b in pb[port]]

A = bus_nets("a"); B = bus_nets("b"); OP = bus_nets("op"); Y = bus_nets("y")

def set_bus(vals, nets, x):
    for i, net in enumerate(nets):
        vals[net] = (x >> i) & 1

def get_bus(allv, nets):
    v = 0
    for i, net in enumerate(nets):
        v |= (allv.get(net, 0) & 1) << i
    return v

def alu_ref(a, b, op):
    a &= 0xFF; b &= 0xFF
    return {0: a & b, 1: a | b, 2: (a + b) & 0xFF,
            3: a ^ b, 6: (a - b) & 0xFF}.get(op, 0)

OPS = {0: "AND", 1: "OR", 2: "ADD", 3: "XOR", 6: "SUB"}

def main():
    print("=== 8-bit ALU hierarchical verification (160 gates) ===")
    phys = verify_physical(verbose=False)
    print(f"[physical] all cell types MCHPRS-verified: {'YES' if phys else 'NO'}")

    import random
    random.seed(1)
    total = ok = 0
    fails = []
    for op, name in OPS.items():
        # exhaustive-ish sample per op
        pairs = [(0, 0), (255, 0), (0, 255), (255, 255), (1, 1),
                 (170, 85), (15, 240), (100, 50), (200, 100), (7, 3)]
        pairs += [(random.randint(0, 255), random.randint(0, 255)) for _ in range(6)]
        op_ok = 0
        for a, b in pairs:
            vals = {}
            set_bus(vals, A, a); set_bus(vals, B, b); set_bus(vals, OP, op)
            # constants
            allv = eval_netlist(nl, vals)
            got = get_bus(allv, Y)
            exp = alu_ref(a, b, op)
            total += 1
            if got == exp:
                ok += 1; op_ok += 1
            else:
                fails.append((name, a, b, got, exp))
        print(f"  {name:4} (op={op:03b}): {op_ok}/{len(pairs)}")
    print(f"[logical] netlist {ok}/{total} vectors match ALU spec")
    if fails:
        for f in fails[:8]:
            print(f"   FAIL {f[0]} a={f[1]} b={f[2]} got={f[3]} exp={f[4]}")
    result = phys and ok == total
    print(f"[RESULT] {'VERIFIED' if result else 'FAILED'}  "
          f"(physical={phys}, logical={ok}/{total})")
    return result

if __name__ == "__main__":
    main()
