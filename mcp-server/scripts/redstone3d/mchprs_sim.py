"""
mchprs_sim.py — Reliable MCHPRS input injection + verification.

Solves the input-injection problem (milestone prerequisite):
  - Runtime APIs (set_lever_power, set_signal_strength, on_use_block) do NOT
    drive the redstone network in this nucleation binding (measured: lever
    is_lit stays False, signal_strength has no effect).
  - RELIABLE method: place redstone_block at input positions in the schematic,
    then create a fresh MchprsWorld. Rebuild per test vector.
    Measured: AND gate 4/4, ~4ms/vector.

Input convention:
  - Each input bit has an INJECTION position (where redstone_block goes for '1')
    feeding a redstone_wire that enters the gate.
  - '1' → minecraft:redstone_block, '0' → minecraft:air at that position.

Output convention:
  - Each output bit is read via world.is_lit(pos) on a redstone_lamp, or
    world.get_redstone_power(pos) > 0 on a wire.
"""
from __future__ import annotations
import nucleation as nuc
from typing import Callable, Dict, List, Tuple, Optional

Pos = Tuple[int, int, int]


def simulate_vectors(
    build_fn: Callable[[nuc.Schematic, Dict[str, int]], None],
    input_names: List[str],
    output_probes: Dict[str, Pos],
    test_vectors: List[Dict[str, int]],
    ticks: int = 10,
    lamp_outputs: bool = True,
    optimize: bool = True,
) -> List[dict]:
    """Run each test vector by rebuilding the schematic with redstone_block inputs.

    Args:
        build_fn: (schem, input_values) -> None. Must place all blocks AND set
                  the input redstone_block/air per input_values.
        input_names: ordered input bit names (for reporting).
        output_probes: name -> absolute (x,y,z) to read.
        test_vectors: list of {"inputs": {name:0/1}, "expected": {name:0/1}}.
        ticks: MCHPRS ticks to settle before reading.
        lamp_outputs: True → read via is_lit; False → read via power>0.

    Returns list of result dicts: {inputs, expected, actual, match}.
    """
    results = []
    for tv in test_vectors:
        inputs = tv.get("inputs", {})
        expected = tv.get("expected", {})

        schem = nuc.Schematic.create("rs3d_vec")
        build_fn(schem, inputs)
        # optimize=True runs the redpiler node-coalescing pass, which both speeds
        # up sim and avoids the direct backend's 255-default-input cap on large
        # circuits (many torches = many default-input nodes without it).
        world = nuc.MchprsWorld.create_with_options(schem, optimize, False)
        world.tick(ticks)

        actual = {}
        for name, pos in output_probes.items():
            if lamp_outputs:
                actual[name] = 1 if world.is_lit(*pos) else 0
            else:
                actual[name] = 1 if world.get_redstone_power(*pos) > 0 else 0

        match = all(actual.get(k) == v for k, v in expected.items())
        results.append({
            "inputs": dict(inputs),
            "expected": dict(expected),
            "actual": actual,
            "match": match,
        })
    return results


def set_input_block(schem: nuc.Schematic, pos: Pos, value: int) -> None:
    """Place redstone_block for 1, air for 0, at an input injection position."""
    schem.set_block_from_string(
        pos[0], pos[1], pos[2],
        "minecraft:redstone_block" if value else "minecraft:air",
    )


def report(name: str, results: List[dict]) -> bool:
    """Print a truth-table report. Returns True if all passed."""
    passed = sum(1 for r in results if r["match"])
    total = len(results)
    print(f"=== {name}: {passed}/{total} {'PASS' if passed == total else 'FAIL'} ===")
    for r in results:
        istr = " ".join(f"{k}={v}" for k, v in r["inputs"].items())
        estr = " ".join(f"{k}={v}" for k, v in r["expected"].items())
        astr = " ".join(f"{k}={v}" for k, v in r["actual"].items())
        mark = "OK" if r["match"] else "X"
        print(f"  [{mark}] {istr}  exp({estr})  got({astr})")
    return passed == total


if __name__ == "__main__":
    # Self-test: the verified planar AND gate
    ox, oy, oz = 5, 5, 5

    def build_and(schem, inputs):
        B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
        for dx in range(-2, 9):
            for dz in range(-1, 4):
                B(dx, -1, dz, "minecraft:stone")
        set_input_block(schem, (ox-2, oy, oz), inputs.get("A", 0))
        set_input_block(schem, (ox-2, oy, oz+2), inputs.get("B", 0))
        B(-1, 0, 0, "minecraft:redstone_wire"); B(-1, 0, 2, "minecraft:redstone_wire")
        B(0, 0, 0, "minecraft:stone"); B(1, 0, 0, "minecraft:redstone_wall_torch[facing=east]")
        B(0, 0, 2, "minecraft:stone"); B(1, 0, 2, "minecraft:redstone_wall_torch[facing=east]")
        B(2, 0, 0, "minecraft:redstone_wire"); B(2, 0, 2, "minecraft:redstone_wire"); B(2, 0, 1, "minecraft:redstone_wire")
        B(3, 0, 1, "minecraft:redstone_wire")
        B(4, 0, 1, "minecraft:stone"); B(5, 0, 1, "minecraft:redstone_wall_torch[facing=east]")
        B(6, 0, 1, "minecraft:redstone_wire"); B(7, 0, 1, "minecraft:redstone_lamp")

    tvs = [
        {"inputs": {"A": a, "B": b}, "expected": {"Q": a & b}}
        for a in (0, 1) for b in (0, 1)
    ]
    res = simulate_vectors(
        build_and, ["A", "B"], {"Q": (ox+7, oy, oz+1)}, tvs, ticks=8,
    )
    ok = report("AND gate (mchprs_sim self-test)", res)
    print("PASS" if ok else "FAIL")
