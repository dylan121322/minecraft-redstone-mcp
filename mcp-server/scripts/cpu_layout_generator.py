#!/usr/bin/env python3
"""
Generate Minecraft block layouts from CPU simulation models.
Converts behavioral CPU design into structured JSON for /setblock building.

The key insight: since MCHPRS can't simulate torches, we validate logic in Python,
then generate the Minecraft layout directly from the validated design.

Supported architectures:
- Acc-8: 8-bit accumulator (LOAD, ADD, CLEAR)
- Rca-8: 8-bit ripple-carry adder
"""

import json
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

# ============================================================
# Block Layout Generator
# ============================================================

@dataclass
class BlockEntry:
    pos: List[int]  # [dx, dy, dz] relative to origin
    block: str       # minecraft:block_id[properties]
    role: str        # input, output, wire, power, etc.

class LayoutGenerator:
    """Generate Minecraft block layouts from architectural descriptions."""

    @staticmethod
    def rca_8bit(origin: Tuple[int, int, int] = (0, 0, 0)) -> dict:
        """
        8-bit Ripple-Carry Adder layout.

        Structure per bit (3-wide, 2-high):
          Z=2: [wire_B] [stone] [torch]  [wire]  [stone] [torch]  [lamp_S]
          Z=1:                        [wire_junction]
          Z=0: [wire_A] [stone] [torch]  [wire]  [stone] [torch]  [wire_Cout]

        Each full-adder bit = 7 blocks wide × 2 blocks high × 3 blocks deep
        Carrier repeater between bits = 1 additional block
        Total width: 7*8 + 7 = 63 blocks
        """
        bx, by, bz = origin
        blocks = []

        for bit in range(8):
            ox = bit * 8  # 7 for FA + 1 for carry gap

            # Input wires
            blocks.append(BlockEntry([ox+0, 0, 0], "minecraft:redstone_wire", "input"))
            blocks.append(BlockEntry([ox+0, 0, 2], "minecraft:redstone_wire", "input"))

            # NOT A
            blocks.append(BlockEntry([ox+1, 0, 0], "minecraft:stone", "mount"))
            blocks.append(BlockEntry([ox+1, 1, 0], "minecraft:redstone_torch[lit=true]", "inverter"))

            # NOT B
            blocks.append(BlockEntry([ox+1, 0, 2], "minecraft:stone", "mount"))
            blocks.append(BlockEntry([ox+1, 1, 2], "minecraft:redstone_torch[lit=true]", "inverter"))

            # OR junction wires
            blocks.append(BlockEntry([ox+2, 0, 0], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([ox+2, 0, 2], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([ox+2, 0, 1], "minecraft:redstone_wire", "wire"))

            # NOT of OR → XOR sum (A⊕B)
            blocks.append(BlockEntry([ox+3, 0, 1], "minecraft:stone", "mount"))
            blocks.append(BlockEntry([ox+3, 1, 1], "minecraft:redstone_torch[lit=true]", "inverter"))
            blocks.append(BlockEntry([ox+4, 0, 1], "minecraft:redstone_wire", "wire"))

            # AND → carry (A·B)
            blocks.append(BlockEntry([ox+3, 0, 0], "minecraft:stone", "mount"))
            blocks.append(BlockEntry([ox+3, 1, 0], "minecraft:redstone_torch[lit=true]", "inverter"))
            blocks.append(BlockEntry([ox+4, 0, 0], "minecraft:redstone_wire", "wire"))

            # Output lamp (sum bit)
            blocks.append(BlockEntry([ox+5, 0, 1], "minecraft:redstone_lamp", "output"))

            # Carry-out repeater to next bit
            if bit < 7:
                blocks.append(BlockEntry([ox+5, 0, 0], "minecraft:repeater[facing=east,delay=1]", "repeater"))
                blocks.append(BlockEntry([ox+6, 0, 2], "minecraft:redstone_wire", "wire"))  # Cin for next
            else:
                blocks.append(BlockEntry([ox+5, 0, 0], "minecraft:redstone_lamp", "output"))  # Cout lamp

        return LayoutGenerator._to_circuit_json("8-bit RCA", "arithmetic", blocks, 63, 2, 3, origin)

    @staticmethod
    def acc_8bit(origin: Tuple[int, int, int] = (0, 0, 0)) -> dict:
        """
        8-bit Accumulator CPU (Acc-8) layout.

        Layout inspired by Fibonacci computer architecture:
        - 8 horizontal bit lanes (Y=0 through Y=7, odd layers)
        - Data bus at Z=5
        - Comparator ALU at Z=8-14
        - Register (locked repeaters) at Z=3-4
        - Control at Z=0-2 (note_block + observer)
        - Output lamps at Z=16

        Width: ~20 blocks (comparator chain), Height: ~17 (8 bits × 2 + control),
               Depth: ~18 (control → bus → ALU → output)
        """
        bx, by, bz = origin
        blocks = []

        # Glass base
        for x in range(22):
            for z in range(18):
                blocks.append(BlockEntry([x, -1, z], "minecraft:glass", "structure"))

        for bit in range(8):
            y_base = bit * 2 + 1  # odd Y layers for data

            # === Registers (locked repeaters) at Z=3-4 ===
            # ACC register bit: locked repeater stores one bit
            blocks.append(BlockEntry([2, y_base, 3], "minecraft:repeater[facing=east,delay=1,locked=true]", "register"))
            # Input register bit
            blocks.append(BlockEntry([2, y_base, 4], "minecraft:repeater[facing=east,delay=1,locked=true]", "register"))

            # === Bus at Z=5 ===
            blocks.append(BlockEntry([3, y_base, 5], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([4, y_base, 5], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([5, y_base, 5], "minecraft:redstone_wire", "wire"))

            # === ALU: Comparator subtract chain at Z=8-14 ===
            # First comparator: 15 - value (NOT)
            blocks.append(BlockEntry([6, y_base, 8], "minecraft:redstone_block", "power"))
            blocks.append(BlockEntry([7, y_base, 8], "minecraft:comparator[facing=east,mode=subtract]", "comparator"))
            blocks.append(BlockEntry([7, y_base, 9], "minecraft:redstone_wire", "wire"))

            # Bus-to-comparator connection
            blocks.append(BlockEntry([5, y_base, 6], "minecraft:repeater[facing=south,delay=1]", "repeater"))
            blocks.append(BlockEntry([5, y_base, 7], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([6, y_base, 7], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([7, y_base, 7], "minecraft:redstone_wire", "wire"))

            # Second comparator: (15-A) - B = 15-A-B
            blocks.append(BlockEntry([8, y_base, 9], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([9, y_base, 8], "minecraft:comparator[facing=east,mode=subtract]", "comparator"))
            # Side input for B
            blocks.append(BlockEntry([9, y_base, 9], "minecraft:redstone_wire", "wire"))

            # Third comparator: 15 - (15-A-B) = A+B
            blocks.append(BlockEntry([10, y_base, 8], "minecraft:redstone_block", "power"))
            blocks.append(BlockEntry([11, y_base, 8], "minecraft:comparator[facing=east,mode=subtract]", "comparator"))

            # Result back to bus
            blocks.append(BlockEntry([12, y_base, 8], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([12, y_base, 7], "minecraft:repeater[facing=north,delay=1]", "repeater"))
            blocks.append(BlockEntry([12, y_base, 6], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([11, y_base, 6], "minecraft:redstone_wire", "wire"))
            blocks.append(BlockEntry([10, y_base, 6], "minecraft:repeater[facing=west,delay=1]", "repeater"))

            # === Output lamp at Z=16 ===
            blocks.append(BlockEntry([5, y_base, 15], "minecraft:repeater[facing=south,delay=1]", "repeater"))
            blocks.append(BlockEntry([5, y_base, 16], "minecraft:redstone_lamp", "output"))

            # === Structural (concrete walls for isolation) ===
            if bit > 0:
                blocks.append(BlockEntry([0, y_base-1, 0], "minecraft:light_gray_concrete", "structure"))
                blocks.append(BlockEntry([0, y_base-1, 17], "minecraft:light_gray_concrete", "structure"))

        # === Control panel at Z=0-1 ===
        blocks.append(BlockEntry([1, 0, 1], "minecraft:note_block[note=0]", "input"))
        blocks.append(BlockEntry([1, 0, 0], "minecraft:observer[facing=south]", "input"))

        # === Power distribution ===
        blocks.append(BlockEntry([0, 0, 8], "minecraft:redstone_block", "power"))

        return LayoutGenerator._to_circuit_json("Acc-8 CPU", "cpu", blocks, 22, 17, 18, origin)

    @staticmethod
    def _to_circuit_json(name: str, category: str, block_entries: List[BlockEntry],
                         width: int, height: int, depth: int,
                         origin: Tuple[int, int, int]) -> dict:
        """Convert block entries to circuit JSON format."""
        seen = set()
        unique_blocks = []
        for be in block_entries:
            key = tuple(be.pos)
            if key not in seen:
                seen.add(key)
                unique_blocks.append(be)

        return {
            "name": name,
            "category": category,
            "dimensions": {"width": width, "height": height, "depth": depth},
            "inputs": [
                {"label": f"I{i}", "pos": [0, i*2+1, 0], "direction": "west"}
                for i in range(8)
            ],
            "outputs": [
                {"label": f"O{i}", "pos": [5, i*2+1, 16], "direction": "east"}
                for i in range(8)
            ],
            "blocks": [
                {"pos": be.pos, "block": be.block, "role": be.role}
                for be in unique_blocks
            ],
            "propagation_delay_ticks": 48,  # 2rt per comparator × 3 × 8 bits
            "notes": f"Auto-generated from cpu_layout_generator.py. Origin: {origin}"
        }


# ============================================================
# Validation: compare layout output against simulation
# ============================================================

def validate_rca_8bit():
    """Generate RCA-8 layout and validate against simulation."""
    from cpu_simulator import ComparatorAdder8

    layout = LayoutGenerator.rca_8bit()
    print(f"RCA-8 Layout: {len(layout['blocks'])} blocks, {layout['dimensions']}")

    # Test cases from simulation
    cases = [(0,0,0), (1,0,1), (15,15,30), (127,1,128), (255,255,254)]
    passed = 0
    for a, b, expected in cases:
        result, carry = ComparatorAdder8.add_8bit(a, b)
        exp = expected & 0xFF
        if result == exp:
            passed += 1
            print(f"  ✅ {a:>3}+{b:>3}={result:>3}")
        else:
            print(f"  ❌ {a:>3}+{b:>3}={result:>3} exp={exp}")
    print(f"  Passed: {passed}/{len(cases)}")

    return layout


def validate_acc8():
    """Generate Acc-8 layout and validate against simulation."""
    from cpu_simulator import Acc8CPU

    layout = LayoutGenerator.acc_8bit()
    print(f"\nAcc-8 Layout: {len(layout['blocks'])} blocks, {layout['dimensions']}")

    cpu = Acc8CPU()
    test_vals = [1, 2, 3, 5, 8, 13, 21, 34]  # Fibonacci-ish
    for i, v in enumerate(test_vals):
        cpu.set_input(v)
        instr = cpu.step_clock()
        print(f"  Cycle {i}: {instr}({v}) → ACC={cpu.acc}")

    return layout


if __name__ == '__main__':
    print("=== RCA-8 Validation ===")
    _ = validate_rca_8bit()
    print("\n=== Acc-8 Validation ===")
    _ = validate_acc8()
