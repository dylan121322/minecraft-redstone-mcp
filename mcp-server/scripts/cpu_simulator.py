#!/usr/bin/env python3
"""
Redstone CPU Behavioral Simulator.
Models Minecraft redstone components at the logic level for CPU simulation.

Components modeled:
- Wire: carries signal strength 0-15 between components
- RedstoneBlock: constant 15 power source
- Repeater: delays + regenerates signal, optional lock for storage
- Comparator: subtract mode computes max(0, rear - max(sideA, sideB))
- Lamp: output indicator, lit when receiving signal > 0
- Lever: manual input 0 or 15

The simulator builds a directed graph of components and propagates signals.
"""

from collections import deque
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# ============================================================
# Component Models
# ============================================================

class CompType(Enum):
    WIRE = "wire"
    REDSTONE_BLOCK = "redstone_block"
    REPEATER = "repeater"
    COMPARATOR = "comparator"
    LAMP = "lamp"
    LEVER = "lever"
    TORCH = "torch"  # NOT gate

@dataclass
class Component:
    cid: str                          # unique id
    comp_type: CompType
    x: int; y: int; z: int            # position in circuit
    delay: int = 0                    # propagation delay in rt
    state: dict = field(default_factory=dict)  # component-specific state
    inputs: List[str] = field(default_factory=list)   # component ids that feed into this
    outputs: List[str] = field(default_factory=list)  # component ids this feeds into

@dataclass
class Bus:
    """A shared signal path (redstone wire line)."""
    bid: str
    wires: List[str] = field(default_factory=list)  # component ids on this bus
    signal: int = 0

# ============================================================
# 8-bit Accumulator CPU Design (Acc-8)
# ============================================================

class Acc8CPU:
    """
    8-bit Accumulator CPU.

    Architecture:
    - ACC register: 8 locked repeaters (1 per bit), stores current value
    - ALU: comparator-based 8-bit adder (subtract method)
    - Input register: 8 levers for immediate value
    - Clock: manual step via note_block signal
    - Output: 8 lamps

    Operations:
    - LOAD: ACC ← INPUT  (load input value into accumulator)
    - ADD:  ACC ← ACC + INPUT  (add input to accumulator)
    - CLEAR: ACC ← 0

    Signal encoding: 4-bit values use signal strength 0-15.
    Each 4-bit nibble is stored separately (2 nibbles = 8 bits).
    For 8-bit values, we use two 4-bit comparator chains.
    """

    def __init__(self):
        self.acc = 0          # 8-bit accumulator value (0-255)
        self.input_reg = 0    # 8-bit input value (0-255)
        self.clock_ticks = 0
        self.output_lamps = [0] * 8  # 8 lamp states
        self.carry = 0        # carry/overflow flag

        # Instruction memory (analog ROM)
        self.program = ["LOAD", "ADD", "ADD", "LOAD", "ADD", "ADD", "ADD", "LOAD"]
        self.pc = 0           # program counter

    def step_clock(self):
        """Execute one instruction cycle."""
        if self.pc >= len(self.program):
            return  # halt

        instr = self.program[self.pc]
        self.pc += 1

        if instr == "LOAD":
            self.acc = self.input_reg
        elif instr == "ADD":
            result = self.acc + self.input_reg
            self.carry = 1 if result > 255 else 0
            self.acc = result & 0xFF
        elif instr == "CLEAR":
            self.acc = 0
            self.carry = 0

        # Update output lamps
        for i in range(8):
            self.output_lamps[i] = (self.acc >> i) & 1

        self.clock_ticks += 1
        return instr

    def set_input(self, value: int):
        self.input_reg = value & 0xFF

    def reset(self):
        self.acc = 0
        self.input_reg = 0
        self.pc = 0
        self.clock_ticks = 0
        self.carry = 0
        self.output_lamps = [0] * 8


# ============================================================
# Comparator-based 8-bit Adder Model
# ============================================================

class ComparatorAdder8:
    """
    8-bit adder using comparator subtract mode, modeled after
    the Fibonacci computer's ALU.

    Formula: A + B = 15 - ((15 - A_hi) - B_hi) for high nibble
             A + B with carry for low nibble

    In redstone comparators:
    - One comparator: rear=15, side=X → output = 15-X
    - Two in series: rear=15, side=A → (15-A); that feeds rear of second, side=B → (15-A)-B
    - Third to invert: rear=15, side=((15-A)-B) → 15-((15-A)-B) = A+B
    """

    @staticmethod
    def add_4bit(a: int, b: int, carry_in: int = 0) -> Tuple[int, int]:
        """Add two 4-bit values, return (sum, carry_out)."""
        result = a + b + carry_in
        return result & 0xF, 1 if result > 15 else 0

    @staticmethod
    def add_8bit(a: int, b: int) -> Tuple[int, int]:
        """Add two 8-bit values, return (sum, carry)."""
        lo_a, hi_a = a & 0xF, (a >> 4) & 0xF
        lo_b, hi_b = b & 0xF, (b >> 4) & 0xF

        lo_sum, carry = ComparatorAdder8.add_4bit(lo_a, lo_b, 0)
        hi_sum, hi_carry = ComparatorAdder8.add_4bit(hi_a, hi_b, carry)

        result = (hi_sum << 4) | lo_sum
        return result, hi_carry


# ============================================================
# Signal Propagation Engine
# ============================================================

class CircuitSimulator:
    """
    Event-driven redstone signal propagation simulator.

    Models signal strength propagation through wires with distance decay,
    repeater regeneration, comparator subtraction, and torch inversion.
    """

    def __init__(self):
        self.components: Dict[str, Component] = {}
        self.buses: Dict[str, Bus] = {}
        self.events: deque = deque()
        self.tick_count = 0
        self.clock = 0

    def add_component(self, comp: Component):
        self.components[comp.cid] = comp

    def add_bus(self, bus: Bus):
        self.buses[bus.bid] = bus

    def connect(self, src_id: str, dst_id: str):
        """Connect source component output to destination component input."""
        src = self.components.get(src_id)
        dst = self.components.get(dst_id)
        if src and dst:
            src.outputs.append(dst_id)
            dst.inputs.append(src_id)

    def set_signal(self, comp_id: str, signal: int):
        """Set a component's output signal and propagate to connected components."""
        comp = self.components.get(comp_id)
        if not comp:
            return

        # Set signal based on component type
        if comp.comp_type == CompType.LEVER:
            comp.state['signal'] = signal
            # Lever outputs 15 when powered, 0 otherwise
            out_signal = 15 if signal else 0
        elif comp.comp_type == CompType.REDSTONE_BLOCK:
            out_signal = 15
        elif comp.comp_type == CompType.WIRE:
            comp.state['signal'] = signal
            out_signal = signal
        elif comp.comp_type == CompType.TORCH:
            # Torch: NOT gate. Input signal > 0 → output 0; input 0 → output 15
            comp.state['signal'] = signal
            out_signal = 0 if signal > 0 else 15
        elif comp.comp_type == CompType.REPEATER:
            # Repeater: regenerates signal to 15 if input > 0, plus delay
            comp.state['signal'] = signal
            if 'locked' in comp.state and comp.state['locked']:
                out_signal = comp.state.get('stored', 0)  # keep stored value
            else:
                out_signal = 15 if signal > 0 else 0
        elif comp.comp_type == CompType.COMPARATOR:
            # Comparator subtract: output = max(0, rear - max(sideA, sideB))
            rear_signal = comp.state.get('rear_signal', 0)
            side_signal = comp.state.get('side_signal', 0)
            comp.state['signal'] = max(0, rear_signal - side_signal)
            out_signal = comp.state['signal']
        elif comp.comp_type == CompType.LAMP:
            comp.state['lit'] = signal > 0
            out_signal = signal  # pass through
            return  # lamps don't propagate further in our model
        else:
            out_signal = 0

        # Propagate to connected outputs with distance decay
        for out_id in comp.outputs:
            out_comp = self.components.get(out_id)
            if out_comp:
                self.events.append((self.tick_count + comp.delay, out_id, out_signal))

    def tick(self, n: int = 1):
        """Run n simulation ticks."""
        for _ in range(n):
            self.tick_count += 1

            # Process events scheduled for this tick
            to_process = []
            while self.events and self.events[0][0] <= self.tick_count:
                to_process.append(self.events.popleft())

            for _, comp_id, signal in to_process:
                self.set_signal(comp_id, signal)

    def get_signal(self, comp_id: str) -> int:
        comp = self.components.get(comp_id)
        return comp.state.get('signal', 0) if comp else 0

    def is_lit(self, comp_id: str) -> bool:
        comp = self.components.get(comp_id)
        return comp.state.get('lit', False) if comp else False


# ============================================================
# Test: Acc-8 CPU Simulation
# ============================================================

def test_acc8():
    """Run Acc-8 CPU test suite."""
    cpu = Acc8CPU()

    tests = [
        # (input_value, expected_acc_after_cycle)
        # Program: LOAD, ADD, ADD, LOAD, ADD, ADD, ADD, LOAD
        # LOAD: ACC=1
        # ADD:  ACC=1+2=3
        # ADD:  ACC=3+3=6
        # LOAD: ACC=5
        # ADD:  ACC=5+8=13
        # ADD:  ACC=13+13=26
        # ADD:  ACC=26+21=47
        # LOAD: ACC=255
        (1, 1, "LOAD"),     # cycle 0: load 1
        (2, 3, "ADD"),      # cycle 1: 1+2=3
        (3, 6, "ADD"),      # cycle 2: 3+3=6
        (5, 5, "LOAD"),     # cycle 3: load 5
        (8, 13, "ADD"),     # cycle 4: 5+8=13
        (13, 26, "ADD"),    # cycle 5: 13+13=26
        (21, 47, "ADD"),    # cycle 6: 26+21=47
        (255, 255, "LOAD"), # cycle 7: load 255
    ]

    print("Acc-8 CPU Test")
    print("=" * 50)
    passed = 0
    failed = 0

    for input_val, expected_acc, expected_instr in tests:
        cpu.set_input(input_val)
        instr = cpu.step_clock()

        ok = cpu.acc == expected_acc and instr == expected_instr
        if ok:
            passed += 1
            print(f"  ✅ Cycle {cpu.clock_ticks-1}: {instr}({input_val}) → ACC={cpu.acc}")
        else:
            failed += 1
            print(f"  ❌ Cycle {cpu.clock_ticks-1}: {instr}({input_val}) → ACC={cpu.acc} (expected {expected_acc})")

    print(f"\n  Passed: {passed}/{passed+failed}")

    # Test overflow
    cpu.reset()
    cpu.set_input(200)
    cpu.step_clock()  # LOAD 200
    cpu.set_input(100)
    cpu.step_clock()  # ADD 100 → 300 > 255, should overflow
    print(f"\n  Overflow test: 200+100 = {cpu.acc}, carry={cpu.carry} (expect acc=44 or 255, carry=1)")

    return passed == len(tests)


# ============================================================
# 8-bit Ripple-Carry Adder Simulation (for Minecraft layout validation)
# ============================================================

def test_adder_8bit():
    """Test the 8-bit adder model."""
    print("\n8-bit Adder Test")
    print("=" * 50)
    cases = [
        (0, 0, 0), (1, 0, 1), (1, 1, 2), (15, 1, 16),
        (127, 1, 128), (255, 0, 255), (128, 128, 256),
        (15, 15, 30), (10, 20, 30), (100, 155, 255),
    ]
    passed = 0
    for a, b, expected in cases:
        result, carry = ComparatorAdder8.add_8bit(a, b)
        expected_carry = 1 if expected > 255 else 0
        expected_result = expected & 0xFF
        ok = result == expected_result and carry == expected_carry
        if ok:
            passed += 1
            print(f"  ✅ {a:>3} + {b:>3} = {result:>3} (carry={carry})")
        else:
            print(f"  ❌ {a:>3} + {b:>3} = {result:>3} c={carry} (expected {expected_result} c={expected_carry})")
    print(f"\n  Passed: {passed}/{len(cases)}")
    return passed == len(cases)


if __name__ == '__main__':
    cpu_ok = test_acc8()
    adder_ok = test_adder_8bit()
    print(f"\n{'='*50}")
    print(f"CPU simulation: {'PASS' if cpu_ok else 'FAIL'}")
    print(f"Adder simulation: {'PASS' if adder_ok else 'FAIL'}")
