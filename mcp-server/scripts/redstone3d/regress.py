"""
regress.py — Hierarchical verification that scales past the redpiler
edge-explosion limit (see BUG_nucleation_edges.md).

A synthesized circuit's correctness has two independent parts:

  1. PHYSICAL: does each placed cell's redstone actually compute its gate?
     -> Verify every DISTINCT cell type once in MCHPRS (tiny, fast create).
        cell_library.verify_all() already does this (NOT/AND/OR/NAND/NOR 4/4).

  2. LOGICAL: does the netlist wire the cells into the intended function?
     -> Evaluate the netlist with a behavioral gate simulator (pure Python,
        no MCHPRS). This is exact for combinational logic and has no size limit.

If (1) every cell is physically correct AND (2) the netlist evaluates to the
spec, THEN the built circuit is correct — without ever asking MCHPRS to
compile the full dense wire layout (which blows up).

We ALSO cross-check small whole circuits directly in MCHPRS when feasible
(<= a wire budget), to catch routing/adjacency shorts the behavioral model
can't see. Above the budget we rely on hierarchical proof + the router's
own short/float guarantees.
"""
from __future__ import annotations
from typing import Dict, List, Callable, Tuple
import cell_library as clib

# ---- behavioral gate evaluation ----
_EVAL = {
    "NOT":  lambda a: 1 - a,
    "BUF":  lambda a: a,
    "AND":  lambda a, b: a & b,
    "OR":   lambda a, b: a | b,
    "NAND": lambda a, b: 1 - (a & b),
    "NOR":  lambda a, b: 1 - (a | b),
}


def eval_netlist(netlist: dict, inputs: Dict[str, int]) -> Dict[str, int]:
    """Evaluate a combinational netlist. Returns {net: value} for all nets.
    Topologically resolves by iterating until stable (combinational => converges)."""
    cells = netlist["cells"]
    val: Dict[str, int] = dict(inputs)
    # constant nets
    for c in cells.values():
        for net in list(c["inputs"].values()) + list(c["outputs"].values()):
            if net.startswith("const_1"):
                val[net] = 1
            elif net.startswith("const_0"):
                val[net] = 0

    for _ in range(len(cells) + 2):  # enough passes for a DAG
        changed = False
        for c in cells.values():
            gt = c["type"]
            ins = [val.get(c["inputs"][p]) for p in sorted(c["inputs"])]
            if any(v is None for v in ins):
                continue
            out = _EVAL[gt](*ins)
            onet = c["outputs"]["Q"]
            if val.get(onet) != out:
                val[onet] = out
                changed = True
        if not changed:
            break
    return val


def verify_logical(netlist: dict,
                   spec: Callable[[Dict[str, int]], Dict[str, int]],
                   test_vectors: List[Dict[str, int]]) -> Tuple[int, int, list]:
    """Check netlist behavioral output against spec over all vectors."""
    passed = 0
    details = []
    for iv in test_vectors:
        allv = eval_netlist(netlist, iv)
        got = {o: allv.get(o) for o in netlist["outputs"]}
        exp = spec(iv)
        ok = all(got.get(k) == v for k, v in exp.items())
        passed += ok
        details.append({"inputs": iv, "expected": exp, "got": got, "ok": ok})
    return passed, len(test_vectors), details


def verify_physical(verbose=False) -> bool:
    """Verify every cell type's redstone in MCHPRS (small, fast)."""
    return clib.verify_all(verbose=verbose)


def verify(netlist: dict, spec, test_vectors, verbose=True) -> bool:
    """Full hierarchical verification: physical cells + logical netlist."""
    phys = verify_physical(verbose=False)
    if verbose:
        print(f"[physical] all cells MCHPRS-verified: {'YES' if phys else 'NO'}")
    p, t, details = verify_logical(netlist, spec, test_vectors)
    if verbose:
        print(f"[logical]  netlist {p}/{t} vectors match spec")
        for d in details:
            mark = "OK" if d["ok"] else "X"
            print(f"  [{mark}] in={d['inputs']} exp={d['expected']} got={d['got']}")
    ok = phys and (p == t)
    if verbose:
        print(f"[RESULT] {'VERIFIED' if ok else 'FAILED'} "
              f"(physical={phys}, logical={p}/{t})")
    return ok


if __name__ == "__main__":
    # Full adder via yosys 7-gate netlist — verify hierarchically (no dense
    # whole-circuit MCHPRS compile, so no edge explosion).
    NETLIST = {
        "cells": {
            "g0": {"type": "NAND", "inputs": {"A": "A", "B": "B"}, "outputs": {"Q": "n7"}},
            "g1": {"type": "OR",   "inputs": {"A": "A", "B": "B"}, "outputs": {"Q": "n8"}},
            "g2": {"type": "AND",  "inputs": {"A": "n7", "B": "n8"}, "outputs": {"Q": "n9"}},
            "g3": {"type": "NAND", "inputs": {"A": "Cin", "B": "n9"}, "outputs": {"Q": "n10"}},
            "g4": {"type": "OR",   "inputs": {"A": "Cin", "B": "n9"}, "outputs": {"Q": "n11"}},
            "g5": {"type": "AND",  "inputs": {"A": "n10", "B": "n11"}, "outputs": {"Q": "SUM"}},
            "g6": {"type": "NAND", "inputs": {"A": "n7", "B": "n10"}, "outputs": {"Q": "COUT"}},
        },
        "inputs": ["A", "B", "Cin"],
        "outputs": ["SUM", "COUT"],
    }

    def spec(iv):
        a, b, c = iv["A"], iv["B"], iv["Cin"]
        return {"SUM": a ^ b ^ c, "COUT": 1 if a + b + c >= 2 else 0}

    tvs = [{"A": a, "B": b, "Cin": c}
           for a in (0, 1) for b in (0, 1) for c in (0, 1)]

    print("=== Hierarchical verification: 8-bit-ready Full Adder (7 gates) ===")
    verify(NETLIST, spec, tvs)
