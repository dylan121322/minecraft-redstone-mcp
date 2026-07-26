"""
synth.py — Synthesis pipeline: netlist → place → route → nucleation.Schematic.

Also provides regression verification: build the synthesized schematic, inject
inputs (redstone_block), simulate in MCHPRS, compare to the expected function.
"""
from __future__ import annotations
from typing import Dict, List, Tuple, Callable, Optional
import nucleation as nuc
from placer import place, Placement
from maze_router import MazeRouter, RouteResult

Pos = Tuple[int, int, int]

W = "minecraft:redstone_wire"
S = "minecraft:stone"


def synthesize(netlist: dict, origin: Pos = (0, 0, 0)):
    """Return (placement, route, build_fn).
    Uses 5-pass rip-up: fast enough for small modules (<50 gates),
    enough retries to resolve typical congestion."""
    pl = place(netlist, origin=origin, col_gap=10, row_gap=6)
    route = MazeRouter(pl, margin=10).route(max_iters=5)

    # Precompute floor extent
    mn, mx = pl.bounds
    fx0, fz0 = mn[0]-3, mn[2]-3
    fx1, fz1 = mx[0]+3, mx[2]+3
    floor_y = origin[1] - 1

    # widen floor to cover raised wires too
    wy_max = origin[1]
    for net, ws in route.wires.items():
        for (x, y, z) in ws:
            wy_max = max(wy_max, y)

    def build_fn(schem: nuc.Schematic, input_values: Dict[str, int]):
        # 1. Single continuous floor slab under everything (one layer at floor_y).
        #    Use fill_cuboid so MCHPRS sees one solid substrate, not thousands of
        #    isolated blocks (which it would count as separate default inputs,
        #    hitting the 255-input backend limit).
        schem.fill_cuboid(fx0, floor_y, fz0, fx1, floor_y, fz1, S)
        # EVERY wire voxel needs a solid support directly below (floating
        # redstone dust misbehaves and can hang redpiler). Base-plane wires
        # sit on the fill; raised wires get their own support column.
        for net, ws in route.wires.items():
            for (x, y, z) in ws:
                if y > floor_y + 1:
                    schem.set_block_from_string(x, y - 1, z, S)
        # repeaters likewise need support below
        for net, reps in route.repeaters.items():
            for (pos, facing) in reps:
                if pos[1] > floor_y + 1:
                    schem.set_block_from_string(pos[0], pos[1]-1, pos[2], S)
        # 2. cells
        for pc in pl.placed.values():
            pc.cell.emit(schem, *pc.origin)
        # 3. wires
        for net, ws in route.wires.items():
            for (x, y, z) in ws:
                schem.set_block_from_string(x, y, z, W)
        # 4. repeaters
        for net, reps in route.repeaters.items():
            for (pos, facing) in reps:
                schem.set_block_from_string(pos[0], pos[1], pos[2],
                                            f"minecraft:repeater[facing={facing},delay=1]")
        # 5. inject primary inputs: redstone_block one block WEST of the PI pos
        for net, pos in pl.primary_inputs.items():
            val = input_values.get(net, 0)
            schem.set_block_from_string(pos[0]-1, pos[1], pos[2],
                                        "minecraft:redstone_block" if val else "minecraft:air")
            # ensure the PI position itself is a wire that carries into the net
            schem.set_block_from_string(pos[0], pos[1], pos[2], W)

    return pl, route, build_fn


def verify(netlist: dict, expected_fn: Callable[[Dict[str, int]], Dict[str, int]],
           test_vectors: List[Dict[str, int]], ticks: int = 20,
           origin: Pos = (0, 0, 0)) -> List[dict]:
    """Synthesize and run test vectors through MCHPRS."""
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from mchprs_sim import simulate_vectors

    pl, route, build_fn = synthesize(netlist, origin)

    # output probes = primary output positions
    probes = dict(pl.primary_outputs)

    def build(schem, inputs):
        build_fn(schem, inputs)

    tvs = []
    for iv in test_vectors:
        tvs.append({"inputs": iv, "expected": expected_fn(iv)})

    results = simulate_vectors(build, list(netlist["inputs"]), probes, tvs,
                               ticks=ticks, lamp_outputs=False)
    return results, pl, route


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from mchprs_sim import report

    # Simplest end-to-end: two NOTs in series = BUF (isolates routing correctness)
    print("### Test 1: NOT->NOT chain (should behave as BUF) ###")
    nl1 = {
        "cells": {
            "n1": {"type": "NOT", "inputs": {"A": "x"}, "outputs": {"Q": "y"}},
            "n2": {"type": "NOT", "inputs": {"A": "y"}, "outputs": {"Q": "z"}},
        },
        "inputs": ["x"],
        "outputs": ["z"],
    }
    res, pl, route = verify(
        nl1, lambda iv: {"z": iv["x"]},
        [{"x": 0}, {"x": 1}], ticks=12,
    )
    report("NOT->NOT (=BUF)", res)
    print(f"  placement: {pl.stats()}, wires: {route.total_wires()}, failed: {route.failed}")

    # Test 2: single AND through the pipeline
    print("\n### Test 2: single AND ###")
    nl2 = {
        "cells": {"a1": {"type": "AND", "inputs": {"A": "p", "B": "q"}, "outputs": {"Q": "r"}}},
        "inputs": ["p", "q"],
        "outputs": ["r"],
    }
    res2, pl2, route2 = verify(
        nl2, lambda iv: {"r": iv["p"] & iv["q"]},
        [{"p": a, "q": b} for a in (0, 1) for b in (0, 1)], ticks=12,
    )
    report("AND (synthesized)", res2)
    print(f"  placement: {pl2.stats()}, wires: {route2.total_wires()}, failed: {route2.failed}")
