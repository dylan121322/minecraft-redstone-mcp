"""
sim_bitparallel.py — Bit-parallel logic simulation (numpy, no GPU needed).

"Non-precise" fast simulation: evaluates the gate-level netlist for a huge batch
of input vectors at once by packing 64 vectors into each uint64 lane and using
numpy bitwise ops. An array of M lanes → 64*M vectors evaluated in one pass.

Exhaustive 8-bit ALU (2^20 vectors) drops from ~14.5 min (scalar eval_netlist)
to sub-second.

This is combinational-only (no timing/glitches) — exactly the "coarse" model
for functional verification. Precise MCHPRS timing sim stays per-slice on CPU.
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Callable

# gate → numpy bitwise op on packed uint64 arrays
def _NOT(a):     return ~a
def _AND(a, b):  return a & b
def _OR(a, b):   return a | b
def _NAND(a, b): return ~(a & b)
def _NOR(a, b):  return ~(a | b)
def _XOR(a, b):  return a ^ b
def _BUF(a):     return a

_OPS1 = {"NOT": _NOT, "BUF": _BUF}
_OPS2 = {"AND": _AND, "OR": _OR, "NAND": _NAND, "NOR": _NOR, "XOR": _XOR}


def _topo_order(nl: dict) -> List[str]:
    """Topologically order cells so every input net is produced before use."""
    driver = {}                      # net -> cell producing it
    for cn, c in nl["cells"].items():
        for net in c["outputs"].values():
            driver[net] = cn
    order = []
    seen = set()
    inputs = set(nl["inputs"])

    def visit(cn):
        if cn in seen:
            return
        seen.add(cn)
        for net in nl["cells"][cn]["inputs"].values():
            if net in inputs:
                continue
            d = driver.get(net)
            if d is not None:
                visit(d)
        order.append(cn)

    for cn in nl["cells"]:
        visit(cn)
    return order


def simulate_batch(nl: dict, input_lanes: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """Evaluate the netlist for a batch of vectors packed as uint64 lanes.

    input_lanes: net_name -> uint64 array (each bit = one vector's value).
    Returns: net_name -> uint64 array for ALL nets (inputs + internal + outputs).
    All arrays share the same length M (=> 64*M vectors)."""
    # infer lane count
    M = len(next(iter(input_lanes.values())))
    ZERO = np.zeros(M, dtype=np.uint64)
    ONES = np.full(M, np.uint64(0xFFFFFFFFFFFFFFFF), dtype=np.uint64)

    val: Dict[str, np.ndarray] = {}
    # primary inputs
    for net in nl["inputs"]:
        val[net] = input_lanes.get(net, ZERO)
    # constants
    for c in nl["cells"].values():
        for net in list(c["inputs"].values()) + list(c["outputs"].values()):
            if net.startswith("const_1"):
                val[net] = ONES
            elif net.startswith("const_0"):
                val[net] = ZERO

    order = _topo_order(nl)
    for cn in order:
        c = nl["cells"][cn]
        gt = c["type"]
        ins = c["inputs"]
        out = c["outputs"]["Q"]
        if gt in _OPS1:
            a = val.get(ins["A"], ZERO)
            val[out] = _OPS1[gt](a)
        elif gt in _OPS2:
            a = val.get(ins["A"], ZERO)
            b = val.get(ins["B"], ZERO)
            val[out] = _OPS2[gt](a, b)
        else:
            val[out] = ZERO
    return val


def pack_vectors(nl: dict, port_bits: dict,
                 vectors: List[Dict[str, int]]) -> Dict[str, np.ndarray]:
    """Pack a list of port-level input dicts into per-net uint64 lanes.

    vectors: list of {port_name: int_value}. Each becomes one bit position.
    Returns net_name -> uint64 array (length = ceil(len(vectors)/64))."""
    N = len(vectors)
    M = (N + 63) // 64
    lanes: Dict[str, np.ndarray] = {}
    # for each input net, build its lane array
    for vi, vec in enumerate(vectors):
        lane_idx = vi // 64
        bit = np.uint64(1) << np.uint64(vi % 64)
        for port, pval in vec.items():
            if port not in port_bits:
                continue
            w = len(port_bits[port])
            for i in range(w):
                b = port_bits[port][i]
                net = f"n{b}" if not isinstance(b, str) else f"const_{b}"
                if net not in lanes:
                    lanes[net] = np.zeros(M, dtype=np.uint64)
                if (pval >> i) & 1:
                    lanes[net][lane_idx] |= bit
    return lanes


def unpack_output(val: Dict[str, np.ndarray], port_bits: dict,
                  port: str, N: int) -> List[int]:
    """Extract a port's integer value for each of the N vectors."""
    w = len(port_bits[port])
    out = [0] * N
    for i in range(w):
        b = port_bits[port][i]
        net = f"n{b}" if not isinstance(b, str) else f"const_{b}"
        lane = val.get(net)
        if lane is None:
            continue
        for vi in range(N):
            bit = (int(lane[vi // 64]) >> (vi % 64)) & 1
            out[vi] |= bit << i
    return out


def verify_exhaustive(nl: dict, port_bits: dict, in_ports: List[str],
                      out_ports: List[str], ref: Callable,
                      max_vectors: int = None) -> dict:
    """Exhaustively (or up to max_vectors) verify netlist against a reference fn.

    in_ports/out_ports: port names. ref(dict_in) -> dict_out (port -> int)."""
    import itertools, time
    widths = {p: len(port_bits[p]) for p in in_ports}
    total_bits = sum(widths.values())
    total = 1 << total_bits
    if max_vectors and total > max_vectors:
        # random sample
        import random
        vecs = []
        for _ in range(max_vectors):
            vecs.append({p: random.randint(0, (1 << widths[p]) - 1) for p in in_ports})
        mode = f"random {max_vectors}"
    else:
        # exhaustive: enumerate all combinations
        vecs = []
        ranges = [range(1 << widths[p]) for p in in_ports]
        for combo in itertools.product(*ranges):
            vecs.append(dict(zip(in_ports, combo)))
        mode = f"exhaustive {total}"

    t = time.time()
    lanes = pack_vectors(nl, port_bits, vecs)
    val = simulate_batch(nl, lanes)
    got = {p: unpack_output(val, port_bits, p, len(vecs)) for p in out_ports}
    dt = time.time() - t

    fails = 0
    first_fail = None
    for vi, vec in enumerate(vecs):
        exp = ref(vec)
        for p in out_ports:
            if got[p][vi] != exp.get(p, 0):
                fails += 1
                if first_fail is None:
                    first_fail = (vec, {p: got[p][vi] for p in out_ports}, exp)
                break
    return {"mode": mode, "vectors": len(vecs), "fails": fails,
            "time_s": round(dt, 3), "rate": int(len(vecs) / dt) if dt > 0 else 0,
            "first_fail": first_fail}


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "riscv_synth"))
    from yosys_frontend import compile_verilog

    # verify the full 8-bit ALU exhaustively for add/sub, sampled for logic ops
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "riscv_synth"))
    nl = compile_verilog("ALU.v", top="ALU")
    pb = nl["port_bits"]

    def alu_ref(v):
        a, b, op = v["data1"], v["data2"], v["ALU_control"]
        r = {0: a & b, 1: a | b, 2: (a + b) & 0xFF, 3: a ^ b, 6: (a - b) & 0xFF}.get(op, 0)
        return {"ALU_result": r}

    print("=== Bit-parallel ALU verification ===")
    # per-op exhaustive over data1×data2 (2^16 each)
    import itertools
    for op, name in [(0, "AND"), (1, "OR"), (2, "ADD"), (3, "XOR"), (6, "SUB")]:
        vecs = [{"data1": a, "data2": b, "ALU_control": op}
                for a in range(256) for b in range(256)]
        import time
        t = time.time()
        lanes = pack_vectors(nl, pb, vecs)
        val = simulate_batch(nl, lanes)
        got = unpack_output(val, pb, "ALU_result", len(vecs))
        dt = time.time() - t
        fails = sum(1 for i, v in enumerate(vecs) if got[i] != alu_ref(v)["ALU_result"])
        print(f"  {name:4}: {len(vecs)} vecs (256×256 exhaustive), {fails} fails, "
              f"{dt:.3f}s = {int(len(vecs)/dt):,} vec/s")
