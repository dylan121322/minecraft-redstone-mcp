"""
verify_buildable.py — L1 validation: route with BuildableRouter, build the
schematic, simulate in MCHPRS, check truth table. MCHPRS models real redstone
so adjacency shorts / floating dust show up as WRONG OUTPUTS. This is the fast
local loop (no bot) that drives router iteration.
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleation as nuc
from placer import place
from route_buildable import BuildableRouter
from build_from_route import emit_blocks
from mchprs_sim import simulate_vectors, report


def _legality_check(res):
    """Count foreign shorts + floating wires directly on a BuildResult."""
    from route_buildable import _PLANE_SHELL
    owner = dict(res.wire_owner)
    # include repeaters as owned voxels
    for net, reps in res.repeaters.items():
        for (pos, _f) in reps:
            owner[pos] = net
    shorts = 0; floats = 0
    supports = res.supports
    occ = None
    for p, net in owner.items():
        x, y, z = p
        # same-plane shell (orthogonal+diagonal) + vertical + diagonal-ramp
        for dx, dz in _PLANE_SHELL:
            o = owner.get((x+dx, y, z+dz))
            if o is not None and o != net:
                shorts += 1
        for dy in (1, -1):
            o = owner.get((x, y+dy, z))
            if o is not None and o != net:
                shorts += 1
        if y > 0:
            sup = (x, y-1, z)
            if sup not in supports and sup not in owner:
                floats += 1
    return shorts // 2, floats


def verify(nl, spec, tvs, col_gap=16, row_gap=10, ticks=16, verbose=True, name="module"):
    pl = place(nl, col_gap=col_gap, row_gap=row_gap)
    r = BuildableRouter(pl, margin=max(12, col_gap))
    res = r.route(verbose=verbose)
    shorts, floats = _legality_check(res)
    print(f"[{name}] wires={res.total_wires()} supports={len(res.supports)} "
          f"reps={sum(len(v) for v in res.repeaters.values())} "
          f"bridges={sum(res.bridges.values())} failed={len(res.failed)} "
          f"shorts={shorts} floats={floats}")
    if res.failed:
        print(f"[{name}] UNROUTED nets: {res.failed[:8]}")

    probes = dict(pl.primary_outputs)

    def build(schem, inputs):
        emit_blocks(schem.set_block_from_string, pl, res, inputs)

    test_vectors = [{"inputs": iv, "expected": spec(iv)} for iv in tvs]
    results = simulate_vectors(build, list(nl["inputs"]), probes, test_vectors,
                               ticks=ticks, lamp_outputs=False)
    ok = report(name, results) if verbose else all(r["match"] for r in results)
    return ok, res, pl


if __name__ == "__main__":
    # T1: two NOTs in series == BUF (isolates routing correctness)
    print("### T1: NOT->NOT (=BUF) ###")
    nl1 = {"cells": {
        "n1": {"type": "NOT", "inputs": {"A": "x"}, "outputs": {"Q": "y"}},
        "n2": {"type": "NOT", "inputs": {"A": "y"}, "outputs": {"Q": "z"}},
    }, "inputs": ["x"], "outputs": ["z"]}
    verify(nl1, lambda iv: {"z": iv["x"]}, [{"x": 0}, {"x": 1}], name="NOT->NOT")

    # T2: single AND
    print("\n### T2: AND ###")
    nl2 = {"cells": {"a1": {"type": "AND", "inputs": {"A": "p", "B": "q"}, "outputs": {"Q": "r"}}},
           "inputs": ["p", "q"], "outputs": ["r"]}
    verify(nl2, lambda iv: {"r": iv["p"] & iv["q"]},
           [{"p": a, "q": b} for a in (0, 1) for b in (0, 1)], name="AND")

    # T3: fan-out x -> NOT,NOT -> OR  (tests branching + a crossing)
    print("\n### T3: fan-out NOT/NOT -> OR ###")
    nl3 = {"cells": {
        "n1": {"type": "NOT", "inputs": {"A": "x"}, "outputs": {"Q": "a"}},
        "n2": {"type": "NOT", "inputs": {"A": "x"}, "outputs": {"Q": "b"}},
        "o1": {"type": "OR", "inputs": {"A": "a", "B": "b"}, "outputs": {"Q": "y"}},
    }, "inputs": ["x"], "outputs": ["y"]}
    verify(nl3, lambda iv: {"y": (1-iv["x"]) | (1-iv["x"])}, [{"x": 0}, {"x": 1}], name="fanout")
