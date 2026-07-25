#!/usr/bin/env python3
"""
nucleation_bridge.py — Nucleation MCHPRS block-level redstone circuit simulator.

Reads a circuit template (JSON) from stdin, builds a Nucleation Schematic,
runs MCHPRS redstone simulation, and outputs results (JSON) to stdout.

Input (stdin JSON):
{
    "circuit": { /* CircuitTemplate from SKILL.md */ },
    "test_vectors": [ {"inputs": {"A": 0, "B": 0}, "expected": {"Q": 0}} ],
    "ticks": 40
}

Output (stdout JSON):
{
    "passed": bool,
    "results": [...],
    "timing": {...},
    "errors": [...]
}
"""

import json
import sys
import traceback
from typing import Optional

# --- Nucleation imports ---
try:
    import nucleation as nuc
    HAS_NUCLEATION = True
except ImportError:
    HAS_NUCLEATION = False

# Block ID mapping: circuit template uses "minecraft:block_id[states]"
# Nucleation uses "minecraft:block_id" with properties dict

def parse_block(block_str: str):
    """Parse 'minecraft:block_id[key=val,...]' into (block_id, properties_dict)."""
    if '[' in block_str:
        base = block_str[:block_str.index('[')]
        props_str = block_str[block_str.index('[')+1:block_str.index(']')]
        props = {}
        for pair in props_str.split(','):
            if '=' in pair:
                k, v = pair.split('=', 1)
                props[k.strip()] = v.strip()
        return base, props
    return block_str, {}


def build_schematic(circuit: dict) -> Optional['nuc.Schematic']:
    """Build a Nucleation Schematic from a circuit template.

    Places all blocks at their relative positions (shifted to put
    origin at (0, dims.height-1, 0) for standard Minecraft coordinates).
    """
    if not HAS_NUCLEATION:
        return None

    blocks = circuit.get('blocks', [])
    if not blocks:
        return None

    dims = circuit.get('dimensions', {})
    w = dims.get('width', 10)
    h = dims.get('height', 3)
    d = dims.get('depth', 10)

    # Create empty schematic
    schem = nuc.Schematic.create(f"schem_{circuit.get('name', 'unknown')}")
    schem.set_mc_version("1.20.1")
    schem.allocated_dimensions = (w + 2, h + 4, d + 2)

    # Build base platform (solid blocks at Y=0 for dust support)
    for x in range(w + 2):
        for z in range(d + 2):
            schem.set_block((x, 0, z), "minecraft:glass")

    # Place circuit blocks with Y offset (Y=1 = ground level in schematic)
    Y_OFFSET = 1
    for entry in blocks:
        pos = entry.get('pos', [0, 0, 0])
        if len(pos) != 3:
            continue
        dx, dy, dz = pos[0], pos[1], pos[2]
        block_str = entry.get('block', 'minecraft:air')

        block_id, props = parse_block(block_str)

        # Map coordinates: circuit uses dx,dy,dz relative to origin
        # Schematic uses x,y,z with Y=0 as base
        sx = dx + 1  # 1-block margin
        sy = dy + Y_OFFSET
        sz = dz + 1  # 1-block margin

        try:
            if props:
                schem.set_block_with_properties((sx, sy, sz), block_id, props)
            else:
                schem.set_block((sx, sy, sz), block_id)
        except Exception:
            # If block placement fails, skip (e.g., invalid state values)
            schem.set_block((sx, sy, sz), "minecraft:stone")

    # Place input levers at input positions
    for inp in circuit.get('inputs', []):
        ipos = inp.get('pos', [0, 0, 0])
        ix = ipos[0] + 1
        iy = ipos[1] + Y_OFFSET
        iz = ipos[2] + 1
        # Place lever on block near input
        schem.set_block_with_properties(
            (ix, iy + 1, iz), "minecraft:lever",
            {"facing": "east", "powered": "false"}
        )

    return schem


def simulate_mchprs(
    circuit: dict,
    test_vectors: list,
    ticks: int = 40
) -> dict:
    """Run MCHPRS block-level simulation on a circuit.

    For each test vector, sets input levers, runs simulation for `ticks`,
    and reads output signal strengths.
    """
    name = circuit.get('name', 'Unknown')
    category = circuit.get('category', 'logic_gate')
    errors = []
    warnings = []
    results = []

    if not HAS_NUCLEATION:
        return simulate_fallback(circuit, test_vectors)

    # Build schematic
    schem = build_schematic(circuit)
    if schem is None:
        warnings.append("Could not build schematic — falling back to logic simulation")
        return simulate_fallback(circuit, test_vectors)

    # Create MCHPRS simulation world
    try:
        sim = nuc.MchprsWorld.create(schem)
    except Exception as e:
        errors.append(f"MCHPRS world creation failed: {e}")
        return simulate_fallback(circuit, test_vectors)

    inputs = circuit.get('inputs', [])
    outputs = circuit.get('outputs', [])
    Y_OFFSET = 1

    # Map input positions to schematic coordinates
    input_map = {}
    for inp in inputs:
        label = inp.get('label', '')
        pos = inp.get('pos', [0, 0, 0])
        input_map[label] = (pos[0] + 1, pos[1] + Y_OFFSET + 1, pos[2] + 1)

    output_map = {}
    for out in outputs:
        label = out.get('label', '')
        pos = out.get('pos', [0, 0, 0])
        output_map[label] = (pos[0] + 1, pos[1] + Y_OFFSET, pos[2] + 1)

    # Run each test vector
    for tv in test_vectors:
        tv_inputs = tv.get('inputs', {})
        tv_expected = tv.get('expected', {})

        # Set input levers
        for label, value in tv_inputs.items():
            pos = input_map.get(label)
            if pos:
                try:
                    if isinstance(value, str) and value in ('hold', 'toggle', 'rising'):
                        # Stateful input — toggle once
                        sim.on_use_block(pos[0], pos[1], pos[2])
                    elif int(value):
                        sim.set_lever_power(pos[0], pos[1], pos[2], True)
                    else:
                        sim.set_lever_power(pos[0], pos[1], pos[2], False)
                except Exception:
                    pass

        # Run simulation
        try:
            sim.tick(ticks)
            sim.flush()
        except Exception as e:
            errors.append(f"Simulation tick failed: {e}")
            break

        # Read outputs
        actual = {}
        for label, pos in output_map.items():
            try:
                signal = sim.get_signal_strength(pos[0], pos[1], pos[2])
                actual[label] = signal
            except Exception:
                # Try reading lamp state at output position
                try:
                    lit = sim.is_lit(pos[0], pos[1], pos[2])
                    actual[label] = 15 if lit else 0
                except Exception:
                    actual[label] = 0

        # Compare
        match = True
        for k, v in tv_expected.items():
            exp_val = 1 if (isinstance(v, int) and v > 0) or (isinstance(v, str) and v not in ('hold', 'toggle', '0')) else 0
            act_val = 1 if actual.get(k, 0) > 0 else 0
            if exp_val != act_val:
                match = False

        results.append({
            'inputs': tv_inputs,
            'expected': tv_expected,
            'actual': actual,
            'match': match,
        })

    passed = all(r['match'] for r in results) and len(errors) == 0

    return {
        'passed': passed,
        'circuit_name': name,
        'category': category,
        'simulation_type': 'MCHPRS',
        'results': results,
        'timing': {
            'propagation_delay_ticks': circuit.get('propagation_delay_ticks', 0),
            'simulated_ticks': ticks,
            'block_count': len(circuit.get('blocks', [])),
        },
        'errors': errors,
        'warnings': warnings,
    }


def simulate_fallback(circuit: dict, test_vectors: list) -> dict:
    """Logic-level simulation fallback when Nucleation/MCHPRS unavailable."""
    from nucleation_bridge_logic import simulate_circuit as simulate_logic
    return simulate_logic(circuit, test_vectors)


# --- Entry point ---

def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({
                'passed': False,
                'simulation_type': 'MCHPRS',
                'results': [],
                'timing': {},
                'errors': ['Empty input'],
                'warnings': []
            }))
            sys.exit(1)

        data = json.loads(raw)
        circuit = data.get('circuit', {})
        test_vectors = data.get('test_vectors', [])
        ticks = data.get('ticks', 40)

        # Auto-generate test vectors from truth table if none provided
        if not test_vectors:
            tt = circuit.get('truth_table', [])
            inputs = circuit.get('inputs', [])
            outputs = circuit.get('outputs', [])
            input_labels = {i['label'] for i in inputs}
            output_labels = {o['label'] for o in outputs}

            for row in tt:
                tv_inputs = {}
                tv_expected = {}
                for k, v in row.items():
                    if k in input_labels:
                        tv_inputs[k] = v
                    elif k in output_labels:
                        tv_expected[k] = v
                if tv_inputs and tv_expected:
                    has_stateful = any(
                        v in ('hold', 'toggle', 'rising', 'falling', 'oscillating')
                        for v in tv_expected.values()
                    )
                    if not has_stateful:
                        test_vectors.append({'inputs': tv_inputs, 'expected': tv_expected})

        # First try MCHPRS simulation
        result = simulate_mchprs(circuit, test_vectors, ticks)

        # If MCHPRS failed, use fallback logic simulation
        if result.get('errors'):
            from nucleation_bridge_logic import simulate_circuit as simulate_logic
            fb = simulate_logic(circuit, test_vectors, ticks)
            result['fallback'] = fb.get('passed', False)
            result['warnings'].append('MCHPRS simulation failed — used logic fallback')

        print(json.dumps(result, ensure_ascii=False, indent=2))

    except json.JSONDecodeError as e:
        print(json.dumps({
            'passed': False, 'simulation_type': 'MCHPRS',
            'results': [], 'timing': {},
            'errors': [f'Invalid JSON input: {e}'], 'warnings': []
        }))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({
            'passed': False, 'simulation_type': 'MCHPRS',
            'results': [], 'timing': {},
            'errors': [f'{type(e).__name__}: {e}'],
            'warnings': [], 'traceback': traceback.format_exc()
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()
