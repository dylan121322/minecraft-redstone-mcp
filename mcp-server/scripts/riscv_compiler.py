"""
RISC-V 8-bit Pipeline CPU → Redstone Compiler
==============================================
Converts ujjwal-2001/RISCV_8bit_pipeline Verilog design to Minecraft redstone.

Architecture:
  5-stage pipeline: IF → ID → EXE → MEM → WB
  11 instructions: ld, sd, beq, add, sub, and, or, xor, not, jal, nop
  Data forwarding, hazard handling via NOPs

Compiler Pipeline:
  Verilog Parse → Gate Decomposition → Redstone Map → Simulate → Build JSON

Configurable scale:
  - NUM_REGS: 4 (default) or 32
  - DATA_MEM: 16B (default) or 256B
  - INST_MEM: 16 instructions (default) or 100
  - PC_SIZE: auto-derived
"""

import json
import sys
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
from enum import Enum
from collections import defaultdict


# ============================================================
# Configurable Parameters
# ============================================================

@dataclass
class CPUConfig:
    """Scale configuration for the RISC-V CPU."""
    num_regs: int = 4          # Number of registers (x0=zero, x1-x{N-1}=GP)
    data_mem_size: int = 16    # Data memory in bytes
    inst_mem_size: int = 16    # Instruction memory in 32-bit words
    pc_size: int = 4           # PC bit width
    data_width: int = 8        # Data path width
    reg_addr_width: int = 2   # Register address width (log2(num_regs))

    def __post_init__(self):
        self.reg_addr_width = max(2, (self.num_regs - 1).bit_length())
        self.pc_size = max(4, (self.inst_mem_size - 1).bit_length())


# ============================================================
# Gate-Level IR
# ============================================================

class GateType(Enum):
    NOT = "NOT"
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    NAND = "NAND"
    NOR = "NOR"
    BUF = "BUF"
    DFF = "DFF"       # D flip-flop (register bit)
    MUX21 = "MUX21"   # 2-to-1 mux (1-bit)
    ADDER = "ADDER"   # Full adder cell
    CONST0 = "CONST0" # Constant 0 (tie low)
    CONST1 = "CONST1" # Constant 1 (tie high)
    ROM_BIT = "ROM_BIT"  # ROM storage bit
    RAM_BIT = "RAM_BIT"  # RAM storage bit


@dataclass
class Cell:
    name: str
    gtype: GateType
    inputs: Dict[str, str] = field(default_factory=dict)
    outputs: Dict[str, str] = field(default_factory=dict)
    pos: Tuple[int, int, int] = (0, 0, 0)
    width: int = 1  # bit width for parameterized cells

@dataclass
class Module:
    name: str
    ports: Dict[str, str] = field(default_factory=dict)
    cells: Dict[str, Cell] = field(default_factory=dict)
    wires: Dict[str, int] = field(default_factory=dict)  # wire name → width
    submodules: Dict[str, 'Module'] = field(default_factory=dict)


# ============================================================
# Gate Layouts (extending hdl_compiler.py)
# ============================================================

GATE_TABLE = {
    "NOT":    {"in": 1, "out": 1, "rt": 1, "blocks": 4,  "size": (3, 2, 1)},
    "AND":    {"in": 2, "out": 1, "rt": 2, "blocks": 12, "size": (5, 2, 3)},
    "OR":     {"in": 2, "out": 1, "rt": 0, "blocks": 4,  "size": (2, 1, 3)},
    "XOR":    {"in": 2, "out": 1, "rt": 2, "blocks": 13, "size": (5, 2, 3)},
    "NAND":   {"in": 2, "out": 1, "rt": 3, "blocks": 16, "size": (6, 2, 3)},
    "NOR":    {"in": 2, "out": 1, "rt": 1, "blocks": 8,  "size": (4, 2, 3)},
    "BUF":    {"in": 1, "out": 1, "rt": 1, "blocks": 2,  "size": (2, 1, 1)},
    "DFF":    {"in": 1, "out": 1, "rt": 1, "blocks": 3,  "size": (3, 1, 1)},
    "MUX21":  {"in": 3, "out": 1, "rt": 3, "blocks": 28, "size": (7, 2, 3)},
    "ADDER":  {"in": 3, "out": 2, "rt": 4, "blocks": 54, "size": (10, 2, 5)},
    "CONST0": {"in": 0, "out": 1, "rt": 0, "blocks": 1,  "size": (1, 1, 1)},
    "CONST1": {"in": 0, "out": 1, "rt": 0, "blocks": 2,  "size": (2, 1, 1)},
    "ROM_BIT":{"in": 1, "out": 1, "rt": 1, "blocks": 4,  "size": (2, 2, 1)},
    "RAM_BIT":{"in": 3, "out": 1, "rt": 2, "blocks": 6,  "size": (4, 2, 2)},
}

GATE_LAYOUTS = {
    "NOT": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "AND": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [3, 0, 1], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [4, 0, 1], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "OR": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [0, 0, 1], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [1, 0, 1], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "XOR": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 1], "block": "minecraft:stone", "role": "mount"},
        {"pos": [2, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [3, 0, 1], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [4, 0, 1], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "BUF": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [1, 0, 0], "block": "minecraft:repeater[facing=east,delay=1]", "role": "repeater"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "DFF": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},
        {"pos": [1, 0, 0], "block": "minecraft:repeater[facing=east,delay=1,locked=true]", "role": "register"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "MUX21": [
        # 1-bit MUX: Y = (S & D1) | (~S & D0)
        # ~S
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},  # S
        {"pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input"},  # D0
        {"pos": [0, 0, 4], "block": "minecraft:redstone_wire", "role": "input"},  # D1
        {"pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},  # ~S
        # ~S & D0
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire"},  # ~S
        {"pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},  # D0
        {"pos": [3, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [3, 0, 2], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [4, 0, 0], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [4, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [4, 0, 1], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [5, 0, 1], "block": "minecraft:stone", "role": "mount"},
        {"pos": [5, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},  # ~S&D0
        # S & D1
        {"pos": [2, 0, 3], "block": "minecraft:redstone_wire", "role": "wire"},  # S (routed)
        {"pos": [2, 0, 5], "block": "minecraft:redstone_wire", "role": "wire"},  # D1 (routed)
        {"pos": [3, 0, 3], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 3], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [3, 0, 5], "block": "minecraft:stone", "role": "mount"},
        {"pos": [3, 1, 5], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [4, 0, 3], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [4, 0, 5], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [4, 0, 4], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [5, 0, 4], "block": "minecraft:stone", "role": "mount"},
        {"pos": [5, 1, 4], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},  # S&D1
        # OR of both paths
        {"pos": [6, 0, 1], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [6, 0, 4], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [6, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},  # junction
        {"pos": [7, 0, 2], "block": "minecraft:redstone_wire", "role": "output"},  # Y
    ],
    "CONST0": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "CONST1": [
        {"pos": [0, 0, 0], "block": "minecraft:redstone_block", "role": "power"},
        {"pos": [1, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "ROM_BIT": [
        # Pre-programmed bit: if value=1, redstone torch on block → wire
        # if value=0, just air (no output)
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},   # address select
        {"pos": [0, 1, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [0, 2, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "rom_cell"},
        {"pos": [1, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
    "RAM_BIT": [
        # RS NOR latch + write gate + read gate
        {"pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input"},  # data_in
        {"pos": [0, 0, 1], "block": "minecraft:redstone_wire", "role": "input"},  # write_en
        {"pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input"},  # read_en
        # RS NOR for storage
        {"pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount"},
        {"pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter"},
        {"pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire"},
        {"pos": [3, 0, 0], "block": "minecraft:redstone_wire", "role": "output"},
    ],
}


# ============================================================
# Step 1: RISC-V Module → Gate-Level Netlist
# ============================================================

class RISCVRTL:
    """Decomposes RISC-V behavioral Verilog into gate-level netlist."""

    def __init__(self, config: CPUConfig = None):
        self.cfg = config or CPUConfig()
        self.modules: Dict[str, Module] = {}
        self.cell_counter = 0

    def _cid(self, prefix="cell") -> str:
        self.cell_counter += 1
        return f"{prefix}_{self.cell_counter}"

    # ---- Primitive builders ----

    def _not(self, mod: Module, inp: str, out: str):
        cid = self._cid("not")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.NOT,
                              inputs={"A": inp}, outputs={"Y": out})

    def _and(self, mod: Module, a: str, b: str, out: str):
        cid = self._cid("and")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.AND,
                              inputs={"A": a, "B": b}, outputs={"Y": out})

    def _or(self, mod: Module, a: str, b: str, out: str):
        cid = self._cid("or")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.OR,
                              inputs={"A": a, "B": b}, outputs={"Y": out})

    def _xor(self, mod: Module, a: str, b: str, out: str):
        cid = self._cid("xor")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.XOR,
                              inputs={"A": a, "B": b}, outputs={"Y": out})

    def _buf(self, mod: Module, inp: str, out: str):
        cid = self._cid("buf")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.BUF,
                              inputs={"A": inp}, outputs={"Y": out})

    def _mux21(self, mod: Module, d0: str, d1: str, s: str, out: str):
        cid = self._cid("mux")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.MUX21,
                              inputs={"D0": d0, "D1": d1, "S": s},
                              outputs={"Y": out})

    def _dff(self, mod: Module, inp: str, out: str):
        cid = self._cid("dff")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.DFF,
                              inputs={"D": inp}, outputs={"Q": out})

    def _const0(self, mod: Module, out: str):
        cid = self._cid("gnd")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.CONST0,
                              inputs={}, outputs={"Y": out})

    def _const1(self, mod: Module, out: str):
        cid = self._cid("vcc")
        mod.cells[cid] = Cell(name=cid, gtype=GateType.CONST1,
                              inputs={}, outputs={"Y": out})

    def _rom_bit(self, mod: Module, addr: str, out: str, value: int):
        cid = self._cid("rom")
        c = Cell(name=cid, gtype=GateType.ROM_BIT,
                 inputs={"ADDR": addr}, outputs={"Y": out})
        c.width = value  # store bit value in width field
        mod.cells[cid] = c

    # ---- MUX_2to1 (N-bit) ----
    def build_mux2to1(self, width: int) -> Module:
        """N-bit 2-to-1 MUX: Y = S ? D1 : D0"""
        m = Module(name=f"mux2to1_{width}b")
        for p in ["S0"]:
            m.ports[p] = "input"
        for i in range(width):
            m.ports[f"D0_{i}"] = "input"
            m.ports[f"D1_{i}"] = "input"
            m.ports[f"Y_{i}"] = "output"
            self._mux21(m, f"D0_{i}", f"D1_{i}", "S0", f"Y_{i}")
        return m

    # ---- ALU (8-bit) ----
    def build_alu(self) -> Module:
        """8-bit ALU: ADD, SUB, AND, OR, XOR, NOT, JUMP.

        Gate decomposition:
          - 8× full adder (for ADD/SUB)
          - 8× AND gate
          - 8× OR gate
          - 8× XOR gate
          - 8× NOT gate
          - MUX tree for function selection
        """
        m = Module(name="ALU")
        W = self.cfg.data_width  # 8

        # Ports
        for i in range(W):
            m.ports[f"data1_{i}"] = "input"
            m.ports[f"data2_{i}"] = "input"
        for i in range(4):
            m.ports[f"ALU_control_{i}"] = "input"
        for i in range(W):
            m.ports[f"ALU_result_{i}"] = "output"
        m.ports["zero"] = "output"

        ctrl = {f"ALU_control_{i}": f"ctrl_{i}" for i in range(4)}

        # Decode ALU operations:
        # AND=0000, OR=0001, ADD=0010, XOR=0011, NOT=0100, SUB=0110, JUMP=1100
        ctrl_bits = {i: f"_ctrl{i}" for i in range(4)}
        for i, w in ctrl_bits.items():
            # just alias for readability
            m.wires[w] = 1

        # Build function units per bit
        for i in range(W):
            a = f"data1_{i}"
            b = f"data2_{i}"

            # NOT: ~data1[i]
            self._not(m, a, f"_not_{i}")

            # AND: data1[i] & data2[i]
            self._and(m, a, b, f"_and_{i}")

            # OR: data1[i] | data2[i]
            self._or(m, a, b, f"_or_{i}")

            # XOR: data1[i] ^ data2[i]
            self._xor(m, a, b, f"_xor_{i}")

        # Full adder chain for ADD/SUB
        # SUB: A - B = A + ~B + 1
        for i in range(W):
            a = f"data1_{i}"
            b = f"data2_{i}"
            # ~B for subtraction
            self._not(m, b, f"_notb_{i}")

        # Build 8-bit ripple-carry adder
        # We use a chain of full adders
        # For ADD: Cin=0, B_sel=B
        # For SUB: Cin=1, B_sel=~B
        # The muxes select between B and ~B per bit based on is_sub
        # is_sub = ctrl[1] & ctrl[2] (ALU_control = 0110)

        # Simplified: build both paths and mux
        for i in range(W):
            a = f"data1_{i}"
            b = f"data2_{i}"

            # Adder with B (for ADD)
            if i == 0:
                # bit 0: A xor B xor Cin(Cin=0) → A xor B
                self._xor(m, a, b, f"_add_sum_{i}")
                # Cout: A&B | Cin&(A^B) → A&B (since Cin=0)
                self._and(m, a, b, f"_add_cout_{i}")
            else:
                # XOR1: A xor B
                self._xor(m, a, b, f"_add_axorb_{i}")
                # Sum: (A xor B) xor Cin
                self._xor(m, f"_add_axorb_{i}", f"_add_cin_{i}", f"_add_sum_{i}")
                # Cout intermediate: A&B
                self._and(m, a, b, f"_add_ab_{i}")
                # Cin & (A xor B)
                self._and(m, f"_add_cin_{i}", f"_add_axorb_{i}", f"_add_cin_xor_{i}")
                # Cout: (A&B) | (Cin & (A xor B))
                self._or(m, f"_add_ab_{i}", f"_add_cin_xor_{i}", f"_add_cout_{i}")

            if i > 0:
                # carry chain
                m.wires[f"_add_cin_{i}"] = 1
                # connect cout[i-1] to cin[i] (done below)
                self._buf(m, f"_add_cout_{i-1}", f"_add_cin_{i}")

        # Sub adder: A + ~B + 1
        for i in range(W):
            a = f"data1_{i}"
            notb = f"_notb_{i}"

            if i == 0:
                # bit 0: sum = A xor ~B xor 1 = ~(A xor ~B) if Cin=1
                self._xor(m, a, notb, f"_sub_axorb_{i}")
                self._not(m, f"_sub_axorb_{i}", f"_sub_sum_{i}")
                # Cout: A&~B | 1&(A^~B)
                self._and(m, a, notb, f"_sub_anb_{i}")
                self._buf(m, f"_sub_axorb_{i}", f"_sub_cin_xor_{i}")
                self._or(m, f"_sub_anb_{i}", f"_sub_cin_xor_{i}", f"_sub_cout_{i}")
            else:
                self._xor(m, a, notb, f"_sub_axorb_{i}")
                self._xor(m, f"_sub_axorb_{i}", f"_sub_cin_{i}", f"_sub_sum_{i}")
                self._and(m, a, notb, f"_sub_anb_{i}")
                self._and(m, f"_sub_cin_{i}", f"_sub_axorb_{i}", f"_sub_cin_xor_{i}")
                self._or(m, f"_sub_anb_{i}", f"_sub_cin_xor_{i}", f"_sub_cout_{i}")

            if i > 0:
                m.wires[f"_sub_cin_{i}"] = 1
                self._buf(m, f"_sub_cout_{i-1}", f"_sub_cin_{i}")

        # MUX: select function output per bit
        # is_add = ~ctrl[3] & ~ctrl[2] & ctrl[1] & ~ctrl[0]  (0010)
        # is_sub = ~ctrl[3] & ctrl[2] & ctrl[1] & ~ctrl[0]   (0110)
        # is_and = ~ctrl[3] & ~ctrl[2] & ~ctrl[1] & ~ctrl[0]  (0000)
        # is_or  = ~ctrl[3] & ~ctrl[2] & ~ctrl[1] & ctrl[0]   (0001)
        # is_xor = ~ctrl[3] & ~ctrl[2] & ctrl[1] & ctrl[0]    (0011)
        # is_not = ~ctrl[3] & ctrl[2] & ~ctrl[1] & ~ctrl[0]   (0100)
        # is_jmp = ctrl[3] & ctrl[2] & ~ctrl[1] & ~ctrl[0]    (1100)

        # We use a MUX tree approach for simplicity
        for i in range(W):
            # Level 0: select between logic functions
            fn_signals = {
                "and": f"_and_{i}",
                "or": f"_or_{i}",
                "xor": f"_xor_{i}",
                "not": f"_not_{i}",
                "add": f"_add_sum_{i}",
                "sub": f"_sub_sum_{i}",
                "zero": f"_gnd",  # JUMP outputs 0
            }
            # Build a priority-encoded MUX tree
            # Stage: ctrl[1:0] selects among {and, or, xor, add} when ctrl[3:2]=00
            self._mux21(m, fn_signals["and"], fn_signals["or"],
                        f"ctrl_0", f"_fn0_{i}")
            self._mux21(m, fn_signals["xor"], fn_signals["add"],
                        f"ctrl_0", f"_fn1_{i}")
            self._mux21(m, f"_fn0_{i}", f"_fn1_{i}",
                        f"ctrl_1", f"_fn01_{i}")

            # ctrl[2]: select {fn01, sub} or {not, zero}
            self._const0(m, f"_zero_bit")  # JUMP → 0
            self._mux21(m, fn_signals["not"], f"_zero_bit",
                        f"ctrl_0", f"_fn2_{i}")
            self._mux21(m, fn_signals["sub"], fn_signals["sub"],
                        f"ctrl_0", f"_fn3_{i}")  # duplicate, will be selected by ctrl[2:1]
            self._mux21(m, f"_fn01_{i}", f"_fn2_{i}",
                        f"ctrl_2", f"_fn012_{i}")

            # ctrl[3]: select normal or JUMP
            self._mux21(m, f"_fn012_{i}", f"_zero_bit",
                        f"ctrl_3", f"ALU_result_{i}")

        # Zero detect: NOR of all ALU_result bits
        # Build as chain: zero = ~(r0 | r1 | ... | r7)
        self._or(m, "ALU_result_0", "ALU_result_1", "_z01")
        self._or(m, "_z01", "ALU_result_2", "_z02")
        self._or(m, "_z02", "ALU_result_3", "_z03")
        self._or(m, "_z03", "ALU_result_4", "_z04")
        self._or(m, "_z04", "ALU_result_5", "_z05")
        self._or(m, "_z05", "ALU_result_6", "_z06")
        self._or(m, "_z06", "ALU_result_7", "_z07")
        self._not(m, "_z07", "zero")

        return m

    # ---- Register File ----
    def build_regfile(self) -> Module:
        """Register file: N×8-bit registers with 2 read ports, 1 write port."""
        m = Module(name="Registers")
        N = self.cfg.num_regs
        AW = self.cfg.reg_addr_width

        # Ports
        for i in range(AW):
            m.ports[f"read_reg1_{i}"] = "input"
            m.ports[f"read_reg2_{i}"] = "input"
            m.ports[f"write_reg_{i}"] = "input"
        for i in range(self.cfg.data_width):
            m.ports[f"write_data_{i}"] = "input"
            m.ports[f"read_data1_{i}"] = "output"
            m.ports[f"read_data2_{i}"] = "output"
        m.ports["reg_write"] = "input"

        # Each register = 8 DFFs
        # x0 is always 0 (no DFFs needed)
        # Write: decoder (AW→N) enables write to one register
        # Read: N:1 MUX per read port per bit

        # For N=4, AW=2:
        # Write decoder: 2→4 one-hot
        #   wsel[0] = ~addr[1] & ~addr[0]
        #   wsel[1] = ~addr[1] & addr[0]
        #   wsel[2] = addr[1] & ~addr[0]
        #   wsel[3] = addr[1] & addr[0]

        # Build write decoder (combinational)
        addr_nots = {}
        for i in range(AW):
            self._not(m, f"write_reg_{i}", f"_wraddr_n{i}")
            addr_nots[i] = f"_wraddr_n{i}"

        for reg_idx in range(N):
            if reg_idx == 0:
                continue  # x0 is hardwired to 0
            # Build AND term for this register's write select
            terms = []
            for i in range(AW):
                if (reg_idx >> i) & 1:
                    terms.append(f"write_reg_{i}")
                else:
                    terms.append(addr_nots[i])
            # Chain ANDs: t0 & t1 & ...
            wsel = f"_wsel_{reg_idx}"
            if len(terms) >= 2:
                self._and(m, terms[0], terms[1], f"{wsel}_01")
                for j in range(2, len(terms)):
                    self._and(m, f"{wsel}_0{j-1}", terms[j], f"{wsel}_0{j}")
                # Final write enable: wsel AND reg_write
                self._and(m, f"{wsel}_0{len(terms)-1}", "reg_write", wsel)
            elif len(terms) == 1:
                self._and(m, terms[0], "reg_write", wsel)
            else:
                self._buf(m, "reg_write", wsel)

        # Register storage: N-1 registers × 8 bits of DFFs
        # DFF with write enable: MUX on input (write_data if wen else Q)
        for reg_idx in range(1, N):
            for bit in range(self.cfg.data_width):
                q = f"_reg_{reg_idx}_b{bit}"
                d = f"_reg_{reg_idx}_b{bit}_next"
                # MUX: reg_write ? write_data : Q (hold)
                self._mux21(m, q, f"write_data_{bit}",
                            f"_wsel_{reg_idx}", d)
                self._dff(m, d, q)

        # Read port MUX: N:1 for each read port, each bit
        # Build as tree of 2:1 MUXes
        def build_read_mux(read_addr_prefix, output_prefix):
            """Build N:1 MUX for one read port."""
            for bit in range(self.cfg.data_width):
                # Collect register outputs
                # For reg 0 (zero): constant 0
                self._const0(m, f"_r0_b{bit}")
                reg_outputs = [f"_r0_b{bit}"] + [
                    f"_reg_{r}_b{bit}" for r in range(1, N)
                ]

                # Build MUX tree: ceil(log2(N)) levels
                # For N=4:
                #   Level 0: mux(r0, r1, addr[0]) and mux(r2, r3, addr[0])
                #   Level 1: mux(l0_out, l1_out, addr[1])
                current = reg_outputs
                level = 0
                while len(current) > 1:
                    next_level = []
                    pair_idx = 0
                    for j in range(0, len(current), 2):
                        a = current[j]
                        b = current[j + 1] if j + 1 < len(current) else current[j]
                        out = f"_{output_prefix}_b{bit}_L{level}_{pair_idx}"
                        sel = f"{read_addr_prefix}_{level}"
                        self._mux21(m, a, b, sel, out)
                        next_level.append(out)
                        pair_idx += 1
                    current = next_level
                    level += 1

                # Last mux output connects to read_data port
                self._buf(m, current[0], f"{output_prefix}_{bit}")

        build_read_mux("read_reg1", "read_data1")
        build_read_mux("read_reg2", "read_data2")

        return m

    # ---- Control Unit ----
    def build_control(self) -> Module:
        """Opcode → Control signals (7-bit opcode → 7 output bits).

        Truth table (from Control.v):
          R-type (0110011): branch=0,mem_read=0,mem_to_reg=0,alu_op=10,mem_write=0,alu_src=0,reg_write=1
          ld     (0000011): branch=0,mem_read=1,mem_to_reg=1,alu_op=00,mem_write=0,alu_src=1,reg_write=1
          sd     (0100011): branch=0,mem_read=0,mem_to_reg=X,alu_op=00,mem_write=1,alu_src=1,reg_write=0
          beq    (1100011): branch=1,mem_read=0,mem_to_reg=X,alu_op=01,mem_write=0,alu_src=0,reg_write=0
          jal    (1101111): branch=1,mem_read=0,mem_to_reg=0,alu_op=11,mem_write=0,alu_src=1,reg_write=1

        Gate decomposition: direct SOP from truth table.
        """
        m = Module(name="Control")
        for i in range(7):
            m.ports[f"opcode_{i}"] = "input"
        m.ports["branch"] = "output"
        m.ports["mem_read"] = "output"
        m.ports["mem_to_reg"] = "output"
        m.ports["alu_op_0"] = "output"
        m.ports["alu_op_1"] = "output"
        m.ports["mem_write"] = "output"
        m.ports["alu_src"] = "output"
        m.ports["reg_write"] = "output"

        # Alias opcode bits for readability
        o = {i: f"opcode_{i}" for i in range(7)}

        # Detect instruction types by opcode matching
        # R-type: 0110011 → o6=0,o5=1,o4=1,o3=0,o2=0,o1=1,o0=1
        # ld:     0000011 → 0000011
        # sd:     0100011 → 0100011
        # beq:    1100011 → 1100011
        # jal:    1101111 → 1101111

        # Negated opcode bits
        no = {}
        for i in range(7):
            self._not(m, o[i], f"_no{i}")
            no[i] = f"_no{i}"

        # R-type: o[5] & o[4] & o[1] & o[0] & ~o[6] & ~o[3] & ~o[2]
        self._and(m, o[5], o[4], "_rtype_a")
        self._and(m, o[1], o[0], "_rtype_b")
        self._and(m, "_rtype_a", "_rtype_b", "_rtype_c")
        self._and(m, "_rtype_c", no[6], "_rtype_d")
        self._and(m, "_rtype_d", no[3], "_rtype_e")
        self._and(m, "_rtype_e", no[2], "_is_rtype")

        # ld: ~o6 & ~o5 & ~o4 & ~o3 & ~o2 & o1 & o0
        self._and(m, no[6], no[5], "_ld_a")
        self._and(m, no[4], no[3], "_ld_b")
        self._and(m, no[2], o[1], "_ld_c")
        self._and(m, "_ld_a", "_ld_b", "_ld_d")
        self._and(m, "_ld_d", "_ld_c", "_ld_e")
        self._and(m, "_ld_e", o[0], "_is_ld")

        # sd: ~o6 & o5 & ~o4 & ~o3 & ~o2 & o1 & o0
        self._and(m, no[6], o[5], "_sd_a")
        self._and(m, no[4], no[3], "_sd_b")
        self._and(m, no[2], o[1], "_sd_c")
        self._and(m, "_sd_a", "_sd_b", "_sd_d")
        self._and(m, "_sd_d", "_sd_c", "_sd_e")
        self._and(m, "_sd_e", o[0], "_is_sd")

        # beq: o6 & o5 & ~o4 & ~o3 & ~o2 & o1 & o0
        self._and(m, o[6], o[5], "_beq_a")
        self._and(m, no[4], no[3], "_beq_b")
        self._and(m, no[2], o[1], "_beq_c")
        self._and(m, "_beq_a", "_beq_b", "_beq_d")
        self._and(m, "_beq_d", "_beq_c", "_beq_e")
        self._and(m, "_beq_e", o[0], "_is_beq")

        # jal: o6 & o5 & ~o4 & o3 & o2 & o1 & o0
        self._and(m, o[6], o[5], "_jal_a")
        self._and(m, no[4], o[3], "_jal_b")
        self._and(m, o[2], o[1], "_jal_c")
        self._and(m, "_jal_a", "_jal_b", "_jal_d")
        self._and(m, "_jal_d", "_jal_c", "_jal_e")
        self._and(m, "_jal_e", o[0], "_is_jal")

        # Control signal SOPs
        # branch = is_beq | is_jal
        self._or(m, "_is_beq", "_is_jal", "branch")

        # mem_read = is_ld
        self._buf(m, "_is_ld", "mem_read")

        # mem_to_reg = is_ld
        self._buf(m, "_is_ld", "mem_to_reg")

        # alu_op[1] = is_rtype | is_jal
        self._or(m, "_is_rtype", "_is_jal", "alu_op_1")
        # alu_op[0] = is_beq | is_jal
        self._or(m, "_is_beq", "_is_jal", "alu_op_0")

        # mem_write = is_sd
        self._buf(m, "_is_sd", "mem_write")

        # alu_src = is_ld | is_sd | is_jal
        self._or(m, "_is_ld", "_is_sd", "_alu_src_a")
        self._or(m, "_alu_src_a", "_is_jal", "alu_src")

        # reg_write = is_rtype | is_ld | is_jal
        self._or(m, "_is_rtype", "_is_ld", "_regw_a")
        self._or(m, "_regw_a", "_is_jal", "reg_write")

        return m

    # ---- ALU Control ----
    def build_alu_control(self) -> Module:
        """alu_op[1:0] + funct[9:0] → alu_control[3:0]"""
        m = Module(name="ALU_Control")
        m.ports["alu_op_0"] = "input"
        m.ports["alu_op_1"] = "input"
        for i in range(10):
            m.ports[f"funct_{i}"] = "input"
        for i in range(4):
            m.ports[f"alu_control_{i}"] = "output"

        ao = {0: "alu_op_0", 1: "alu_op_1"}
        f = {i: f"funct_{i}" for i in range(10)}

        # Negated alu_op
        nao = {}
        for i in range(2):
            self._not(m, ao[i], f"_nao{i}")
            nao[i] = f"_nao{i}"

        # Detect alu_op cases:
        # alu_op=00: ADD (0010)
        # alu_op=01: SUBTRACT (0110)
        # alu_op=10: decode funct → {add, sub, and, or, xor, not}
        # alu_op=11: JUMP (1100)

        # alu_op=00 → add
        self._and(m, nao[1], nao[0], "_is_op00")
        # alu_op=01 → sub
        self._and(m, nao[1], ao[0], "_is_op01")
        # alu_op=10 → R-type (decode funct)
        self._and(m, ao[1], nao[0], "_is_op10")
        # alu_op=11 → jump
        self._and(m, ao[1], ao[0], "_is_op11")

        # For alu_op=10, decode funct:
        # funct = {funct7[6:0], funct3[2:0]} = f[9:3], f[2:0]
        # add:  funct7=0000000, funct3=000 → ~f9&~f8&...&~f0
        # sub:  funct7=0100000, funct3=000 → f8 & ~others
        # and:  funct7=0000000, funct3=111 → ~f9..~f3 & f2&f1&f0
        # or:   funct7=0000000, funct3=110 → ~f9..~f3 & f2&f1&~f0
        # xor:  funct7=0000000, funct3=100 → ~f9..~f3 & f2&~f1&~f0  (note: funct3=011 per table)
        # not:  funct7=0000000, funct3=100 → same as xor! (xori)
        # Simplified: decode based on funct3 only (since funct7 only matters for add vs sub)

        # Negated funct3 bits
        nf = {}
        for i in range(3):
            self._not(m, f[i], f"_nf{i}")
            nf[i] = f"_nf{i}"

        # funct3 decodes:
        # 000: add/sub → f8 distinguishes (f8=1→sub, f8=0→add)
        self._and(m, nf[2], nf[1], "_f3_a")
        self._and(m, "_f3_a", nf[0], "_f3_000")

        # 111: and
        self._and(m, f[2], f[1], "_f3_b")
        self._and(m, "_f3_b", f[0], "_f3_111")

        # 110: or
        self._and(m, f[2], f[1], "_f3_c")
        self._and(m, "_f3_c", nf[0], "_f3_110")

        # 100: xor
        self._and(m, f[2], nf[1], "_f3_d")
        self._and(m, "_f3_d", nf[0], "_f3_100")

        # funct7[5]=f[8] → distinguishes add(0) from sub(1)
        self._and(m, "_is_op10", f[8], "_is_funct_sub")
        self._and(m, "_is_op10", "_f3_000", "_is_funct_addsub")
        self._not(m, f[8], "_nf8")
        self._and(m, "_is_funct_addsub", "_nf8", "_is_funct_add")

        # Final alu_control[3:0] = {c3, c2, c1, c0}
        # AND = 0000, OR = 0001, ADD = 0010, XOR = 0011, NOT = 0100, SUB = 0110, JUMP = 1100

        # c0 = OR | XOR | is_op00 (ADD) | is_funct_sub (SUB when op10)
        self._or(m, "_is_op00", "_is_op01", "_c0_a")   # add(00) or sub(01)
        self._or(m, "_is_op11", "_is_op11", "_c0_b")    # jump: c0=0 → NOP
        # c0=1 for: OR(0001), XOR(0011), ADD(0010), SUB(0110)
        self._and(m, "_is_op10", "_f3_110", "_c0_or")
        self._and(m, "_is_op10", "_f3_100", "_c0_xor")
        self._or(m, "_c0_or", "_c0_xor", "_c0_rtype")
        self._or(m, "_c0_a", "_c0_rtype", "alu_control_0")

        # c1 = XOR(11) | NOT(100) | SUB(110) | JUMP(1100) → c1=1
        self._and(m, "_is_op10", "_f3_100", "_c1_xor")
        self._and(m, "_is_op10", "_f3_110", "_c1_or_f")
        self._or(m, "_c1_xor", "_c1_or_f", "_c1_rtype")
        self._or(m, "_c1_rtype", "_is_op01", "_c1_a")  # sub (op01)
        self._or(m, "_c1_a", "_is_op11", "alu_control_1")

        # c2 = SUB(100) | JUMP(1100) → c2=1
        # AND is 0000, OR is 0001, ADD is 0010, XOR is 0011 → c2=0
        # NOT is 0100 (c2=1!), SUB is 0110 (c2=1), JUMP is 1100 (c2=1)
        self._and(m, "_is_op10", "_f3_100", "_c2_not")  # NOT: c2=1
        self._or(m, "_c2_not", "_is_funct_sub", "_c2_a")  # SUB
        self._or(m, "_c2_a", "_is_op01", "_c2_b")  # SUB via op=01
        self._or(m, "_c2_b", "_is_op11", "alu_control_2")

        # c3 = JUMP only
        self._buf(m, "_is_op11", "alu_control_3")

        return m

    # ---- Immediate Generator ----
    def build_imm_gen(self) -> Module:
        """Extract 12-bit immediate from 32-bit instruction based on opcode."""
        m = Module(name="Imm_Gen")
        for i in range(32):
            m.ports[f"instruction_{i}"] = "input"
        for i in range(12):
            m.ports[f"immediate_{i}"] = "output"

        inst = {i: f"instruction_{i}" for i in range(32)}

        # Opcode = inst[6:0]
        o = {i: inst[i] for i in range(7)}
        no = {}
        for i in range(7):
            self._not(m, o[i], f"_no{i}")
            no[i] = f"_no{i}"

        # Detect instruction types by opcode:
        # I-type: opcode = 000_xxxx → ~o6 & ~o5 & ~o4 = 000xxxx
        self._and(m, no[6], no[5], "_itype_a")
        self._and(m, "_itype_a", no[4], "_is_itype")

        # R-type: opcode = 011_xxxx → ~o6 & o5 & o4 = 011xxxx
        self._and(m, no[6], o[5], "_rtype_a")
        self._and(m, "_rtype_a", o[4], "_is_rtype")

        # S-type/SB-type: opcode = 010_xxxx (sd) or 110_0xxx (beq)
        self._and(m, no[6], o[5], "_stype_a")
        self._and(m, "_stype_a", no[4], "_is_stype")

        # UJ-type: opcode = 110_1xxx (jal) → o6 & o5 & ~o4 & o3
        self._and(m, o[6], o[5], "_uj_a")
        self._and(m, "_uj_a", no[4], "_uj_b")
        self._and(m, "_uj_b", o[3], "_is_ujtype")

        # Immediate routing per bit:
        # I-type: immediate = inst[31:20] (12 bits)
        # S/SB-type: immediate = {inst[31:25], inst[11:7]} (12 bits)
        # UJ-type: immediate = inst[31:20] (simplified - actually bit-shifted)

        # For each bit position in the 12-bit immediate, MUX in the correct source
        for i in range(12):
            if i < 5:
                # bits [4:0]: I-type uses inst[24:20], S-type uses inst[11:7], UJ uses inst[24:20]
                i_src = inst[20 + i]  # I-type: inst[24:20]
                s_src = inst[7 + i]   # S-type: inst[11:7]

                # MUX between I-type and S-type based on is_stype
                self._mux21(m, i_src, s_src, "_is_stype_or_uj",
                            f"_imm_sel_{i}")
                # is_stype_or_uj = is_stype OR is_ujtype
                self._or(m, "_is_stype", "_is_ujtype", f"_is_stype_or_uj_{i}")

            elif i < 12:
                # bits [11:5]: I-type uses inst[31:25], S-type uses inst[31:25], UJ uses inst[31:25]
                # All three use the same bits! Just route directly
                self._buf(m, inst[25 + (i - 5)], f"immediate_{i}")

        # Connect the lower 5 bits that need muxing
        for i in range(5):
            self._buf(m, f"_imm_sel_{i}", f"immediate_{i}")

        return m

    # ---- Forwarding Unit ----
    def build_forwarding_unit(self) -> Module:
        """Comparator-based forwarding: checks if EX/MEM or MEM/WB dest matches RS1/RS2."""
        m = Module(name="Forwarding_Unit")
        AW = self.cfg.reg_addr_width

        for i in range(AW):
            m.ports[f"reg_RS1_{i}"] = "input"
            m.ports[f"reg_RS2_{i}"] = "input"
            m.ports[f"ex_mem_reg_RD_{i}"] = "input"
            m.ports[f"mem_wb_reg_RD_{i}"] = "input"
        m.ports["ex_mem_regwrite"] = "input"
        m.ports["mem_wb_regwrite"] = "input"
        m.ports["fwd_A_0"] = "output"
        m.ports["fwd_A_1"] = "output"
        m.ports["fwd_B_0"] = "output"
        m.ports["fwd_B_1"] = "output"

        # Equality check: two AW-bit values equal
        def build_eq(a_prefix, b_prefix, out):
            """XNOR each bit → AND all together = equality."""
            eq_bits = []
            for i in range(AW):
                a = f"{a_prefix}_{i}"
                b = f"{b_prefix}_{i}"
                self._xor(m, a, b, f"{out}_xor_{i}")
                self._not(m, f"{out}_xor_{i}", f"{out}_eq_{i}")
                eq_bits.append(f"{out}_eq_{i}")
            # AND chain all eq bits
            if len(eq_bits) >= 2:
                self._and(m, eq_bits[0], eq_bits[1], f"{out}_and01")
                for j in range(2, len(eq_bits)):
                    self._and(m, f"{out}_and0{j-1}", eq_bits[j], f"{out}_and0{j}")
                self._buf(m, f"{out}_and0{len(eq_bits)-1}", out)
            else:
                self._buf(m, eq_bits[0], out)

        # RS1 == EX/MEM.RD
        build_eq("reg_RS1", "ex_mem_reg_RD", "_rs1_eq_ex")
        # RS1 == MEM/WB.RD
        build_eq("reg_RS1", "mem_wb_reg_RD", "_rs1_eq_mem")
        # RS2 == EX/MEM.RD
        build_eq("reg_RS2", "ex_mem_reg_RD", "_rs2_eq_ex")
        # RS2 == MEM/WB.RD
        build_eq("reg_RS2", "mem_wb_reg_RD", "_rs2_eq_mem")

        # Forwarding logic:
        # fwd_A = 2'b10 if (ex_mem_regwrite && ex_mem_reg_RD != 0 && RS1 == EX/MEM.RD)
        #       = 2'b01 if (mem_wb_regwrite && mem_wb_reg_RD != 0 && RS1 == MEM/WB.RD)
        #       = 2'b00 otherwise
        # (similarly for fwd_B)

        # fwd_A[0] → forward from MEM/WB
        self._and(m, "mem_wb_regwrite", "_rs1_eq_mem", "_fwdA_mem")
        self._buf(m, "_fwdA_mem", "fwd_A_0")

        # fwd_A[1] → forward from EX/MEM
        self._and(m, "ex_mem_regwrite", "_rs1_eq_ex", "_fwdA_ex")
        self._buf(m, "_fwdA_ex", "fwd_A_1")

        # fwd_B[0]
        self._and(m, "mem_wb_regwrite", "_rs2_eq_mem", "_fwdB_mem")
        self._buf(m, "_fwdB_mem", "fwd_B_0")

        # fwd_B[1]
        self._and(m, "ex_mem_regwrite", "_rs2_eq_ex", "_fwdB_ex")
        self._buf(m, "_fwdB_ex", "fwd_B_1")

        return m

    # ---- Pipeline Register (generic) ----
    def build_pipeline_reg(self, name: str, signals: Dict[str, int]) -> Module:
        """Generic pipeline register: list of (signal_name, width) → DFF per bit."""
        m = Module(name=name)
        for sig, width in signals.items():
            for i in range(width):
                m.ports[f"{sig}_in_{i}"] = "input"
                m.ports[f"{sig}_out_{i}"] = "output"
                self._dff(m, f"{sig}_in_{i}", f"{sig}_out_{i}")
        return m

    # ---- Data Memory ----
    def build_data_memory(self) -> Module:
        """Data memory: simplified RAM (uses RAM_BIT cells)."""
        m = Module(name="Data_Memory")
        SIZE = self.cfg.data_mem_size
        AW = (SIZE - 1).bit_length()
        DW = self.cfg.data_width

        for i in range(AW):
            m.ports[f"address_{i}"] = "input"
        for i in range(DW):
            m.ports[f"write_data_{i}"] = "input"
            m.ports[f"read_data_{i}"] = "output"
        m.ports["mem_write"] = "input"
        m.ports["mem_read"] = "input"

        # Address decoder: AW→SIZE one-hot
        # ... Build address decoder
        # For each byte: RAM_BIT × 8 with write_en and read_en gating
        # Simplified: address decoder + per-address latch

        # Actually for the demo: use a behavioral model during simulation
        # and abstract blocks for build stage
        # Mark as abstract (simulated behaviorally, built as pre-wired ROM)
        self._const0(m, f"read_data_0")
        for i in range(1, DW):
            self._buf(m, "read_data_0", f"read_data_{i}")

        return m

    # ---- Instruction Memory (ROM) ----
    def build_inst_memory(self) -> Module:
        """Instruction memory as ROM (pre-programmed)."""
        m = Module(name="Instruction_Memory")
        SIZE = self.cfg.inst_mem_size
        AW = self.cfg.pc_size

        for i in range(AW):
            m.ports[f"read_address_{i}"] = "input"
        for i in range(32):
            m.ports[f"instruction_out_{i}"] = "output"

        # ROM: address decoder → word select → ROM_BIT per bit
        # Each instruction word: 32 ROM_BITs
        # Address decoder: AW→SIZE one-hot

        # Build address decoder
        addr_wires = [f"read_address_{i}" for i in range(AW)]
        # Negate all address bits
        naddr = {}
        for i in range(AW):
            self._not(m, addr_wires[i], f"_naddr_{i}")
            naddr[i] = f"_naddr_{i}"

        # For each instruction slot, generate word select
        for slot in range(SIZE):
            terms = []
            for i in range(AW):
                if (slot >> i) & 1:
                    terms.append(addr_wires[i])
                else:
                    terms.append(naddr[i])
            if len(terms) >= 2:
                self._and(m, terms[0], terms[1], f"_wsel_{slot}_01")
                for j in range(2, len(terms)):
                    self._and(m, f"_wsel_{slot}_0{j-1}", terms[j],
                              f"_wsel_{slot}_0{j}")
                m.wires[f"_wsel_{slot}"] = 1
                self._buf(m, f"_wsel_{slot}_0{len(terms)-1}", f"_wsel_{slot}")
            else:
                self._buf(m, terms[0], f"_wsel_{slot}")

        # For each bit of each instruction, ROM_BIT (value stored in cell.width)
        for slot in range(SIZE):
            for bit in range(32):
                out = f"_inst_{slot}_b{bit}"
                self._rom_bit(m, f"_wsel_{slot}", out, 0)  # value=0 placeholder

        # Output MUX: OR-tree of all slots (only one wsel active at a time)
        for bit in range(32):
            # Collect all slot outputs for this bit
            slot_outs = [f"_inst_{s}_b{bit}" for s in range(SIZE)]
            # OR them all together
            current = slot_outs[0]
            for s in range(1, SIZE):
                self._or(m, current, slot_outs[s], f"_out_or_{bit}_{s}")
                current = f"_out_or_{bit}_{s}"
            self._buf(m, current, f"instruction_out_{bit}")

        return m

    # ============================================================
    # TOP-LEVEL: Build complete RISC-V CPU netlist
    # ============================================================

    def build_cpu(self) -> Module:
        """Assemble the complete RISC-V 8-bit pipeline CPU."""
        top = Module(name="RISC_V_CPU")
        cfg = self.cfg
        W = cfg.data_width
        AW = cfg.reg_addr_width
        PC = cfg.pc_size

        # ---- Build submodules ----
        alu = self.build_alu()
        control = self.build_control()
        alu_ctrl = self.build_alu_control()
        regfile = self.build_regfile()
        imm_gen = self.build_imm_gen()
        fwd_unit = self.build_forwarding_unit()
        inst_mem = self.build_inst_memory()
        data_mem = self.build_data_memory()

        # Store submodules for later extraction
        top.submodules["ALU"] = alu
        top.submodules["Control"] = control
        top.submodules["ALU_Control"] = alu_ctrl
        top.submodules["Registers"] = regfile
        top.submodules["Imm_Gen"] = imm_gen
        top.submodules["Forwarding_Unit"] = fwd_unit
        top.submodules["Instruction_Memory"] = inst_mem
        top.submodules["Data_Memory"] = data_mem

        # ---- Pipeline registers ----
        # IF/ID: PC_out(PC), instruction(32)
        if_id = self.build_pipeline_reg("IF_ID", {
            "pc": PC, "inst": 32
        })
        # ID/EX: control(8) + data1(W) + data2(W) + imm(12) + funct(10) + PC(PC) + wr(W) + rs1(AW) + rs2(AW)
        id_ex = self.build_pipeline_reg("ID_EX", {
            "branch": 1, "mem_read": 1, "mem_to_reg": 1,
            "alu_op": 2, "mem_write": 1, "alu_src": 1, "reg_write": 1,
            "data1": W, "data2": W, "imm": 12, "funct": 10,
            "pc": PC, "wr": AW, "rs1": AW, "rs2": AW
        })
        # EX/MEM: branch(1) + mem_read(1) + mem_to_reg(1) + mem_write(1) + ALU_result(W) + write_data(W) + zero(1) + reg_write(1) + wr(AW)
        ex_mem = self.build_pipeline_reg("EX_MEM", {
            "branch": 1, "mem_read": 1, "mem_to_reg": 1,
            "mem_write": 1, "alu_result": W, "write_data": W,
            "zero": 1, "reg_write": 1, "wr": AW
        })
        # MEM/WB: mem_to_reg(1) + read_data(W) + ALU_result(W) + reg_write(1) + wr(AW)
        mem_wb = self.build_pipeline_reg("MEM_WB", {
            "mem_to_reg": 1, "read_data": W, "alu_result": W,
            "reg_write": 1, "wr": AW
        })

        top.submodules["IF_ID"] = if_id
        top.submodules["ID_EX"] = id_ex
        top.submodules["EX_MEM"] = ex_mem
        top.submodules["MEM_WB"] = mem_wb

        return top

    # ============================================================
    # Statistics & Reporting
    # ============================================================

    def count_cells(self, mod: Module, recurse: bool = True) -> Dict[str, int]:
        """Count cells by type."""
        counts = defaultdict(int)
        for cell in mod.cells.values():
            counts[cell.gtype.value] += 1
        if recurse:
            for sub in mod.submodules.values():
                sub_counts = self.count_cells(sub, recurse=True)
                for k, v in sub_counts.items():
                    counts[k] += v
        return dict(counts)

    def estimate_blocks(self, mod: Module, recurse: bool = True) -> int:
        """Estimate total Minecraft blocks needed."""
        total = 0
        for cell in mod.cells.values():
            total += GATE_TABLE.get(cell.gtype.value, {}).get("blocks", 4)
        if recurse:
            for sub in mod.submodules.values():
                total += self.estimate_blocks(sub, recurse=True)
        return total

    def estimate_delay(self, mod: Module) -> int:
        """Estimate critical path delay in redstone ticks."""
        # For pipelined CPU, critical path is the longest combinational stage
        # (typically EXE stage: ALU + MUXes)
        exe_delay = 0
        if "ALU" in mod.submodules:
            exe_delay += self.estimate_delay(mod.submodules["ALU"])
        if "Forwarding_Unit" in mod.submodules:
            exe_delay += self.estimate_delay(mod.submodules["Forwarding_Unit"])
        return exe_delay


# ============================================================
# Step 3: Simulation (Cycle-Accurate Behavioral)
# ============================================================

class RISCVRTLSimulator:
    """Cycle-accurate behavioral simulator for the RISC-V pipeline CPU.

    Models each pipeline stage as a function that computes next state
    from current state. Handles forwarding and pipeline stalls.
    """

    def __init__(self, config: CPUConfig = None):
        self.cfg = config or CPUConfig()
        W = self.cfg.data_width
        PC = self.cfg.pc_size
        AW = self.cfg.reg_addr_width

        # Architectural state
        self.registers = [0] * self.cfg.num_regs  # x0-x{N-1}, x0 hardwired to 0
        self.data_memory = [0] * (self.cfg.data_mem_size + 10)  # prefilled with test data
        self.inst_memory = [0] * self.cfg.inst_mem_size  # 32-bit instructions
        self.PC = 0

        # Pipeline registers
        self.IF_ID = {"pc": 0, "inst": 0, "valid": False}
        self.ID_EX = {"pc": 0, "data1": 0, "data2": 0, "imm": 0, "funct": 0,
                      "branch": 0, "mem_read": 0, "mem_to_reg": 0,
                      "alu_op": 0, "mem_write": 0, "alu_src": 0, "reg_write": 0,
                      "wr": 0, "rs1": 0, "rs2": 0, "valid": False}
        self.EX_MEM = {"branch": 0, "mem_read": 0, "mem_to_reg": 0, "mem_write": 0,
                       "alu_result": 0, "write_data": 0, "zero": 0, "reg_write": 0,
                       "wr": 0, "valid": False}
        self.MEM_WB = {"mem_to_reg": 0, "read_data": 0, "alu_result": 0,
                       "reg_write": 0, "wr": 0, "valid": False}

        # Pipeline stall tracking (for NOP insertion)
        self.stall_count = 0
        self.total_instructions = 0
        self.cycles = 0

    def load_program(self, instructions: List[int], data: List[int] = None):
        """Load instructions and data into memories."""
        for i, inst in enumerate(instructions):
            self.inst_memory[i] = inst
        if data:
            for i, d in enumerate(data):
                self.data_memory[i] = d

    def _decode_instruction(self, inst: int) -> dict:
        """Decode a 32-bit RISC-V instruction."""
        opcode = inst & 0x7F
        rd = (inst >> 7) & 0x1F
        funct3 = (inst >> 12) & 0x7
        rs1 = (inst >> 15) & 0x1F
        rs2 = (inst >> 20) & 0x1F
        funct7 = (inst >> 25) & 0x7F
        return {"opcode": opcode, "rd": rd, "funct3": funct3,
                "rs1": rs1, "rs2": rs2, "funct7": funct7,
                "imm_i": (inst >> 20) & 0xFFF,
                "imm_s": ((funct7 << 5) | (rd & 0x1F)),
                "imm_uj": (inst >> 20) & 0xFFF}

    def _control(self, opcode: int) -> dict:
        """Control unit: opcode → control signals."""
        ctrl = {"branch": 0, "mem_read": 0, "mem_to_reg": 0,
                "alu_op": 0, "mem_write": 0, "alu_src": 0, "reg_write": 0,
                "write_reg": 0}

        if opcode == 0b0110011:  # R-type
            ctrl = {"branch": 0, "mem_read": 0, "mem_to_reg": 0,
                    "alu_op": 2, "mem_write": 0, "alu_src": 0, "reg_write": 1}
        elif opcode == 0b0000011:  # ld
            ctrl = {"branch": 0, "mem_read": 1, "mem_to_reg": 1,
                    "alu_op": 0, "mem_write": 0, "alu_src": 1, "reg_write": 1}
        elif opcode == 0b0100011:  # sd
            ctrl = {"branch": 0, "mem_read": 0, "mem_to_reg": 0,
                    "alu_op": 0, "mem_write": 1, "alu_src": 1, "reg_write": 0}
        elif opcode == 0b1100011:  # beq
            ctrl = {"branch": 1, "mem_read": 0, "mem_to_reg": 0,
                    "alu_op": 1, "mem_write": 0, "alu_src": 0, "reg_write": 0}
        elif opcode == 0b1101111:  # jal
            ctrl = {"branch": 1, "mem_read": 0, "mem_to_reg": 0,
                    "alu_op": 3, "mem_write": 0, "alu_src": 1, "reg_write": 1}
        # else: NOP/all zeros

        return ctrl

    def _alu_control(self, alu_op: int, funct7: int, funct3: int) -> int:
        """ALU control: alu_op + funct → 4-bit ALU control."""
        # AND=0, OR=1, ADD=2, XOR=3, NOT=4, SUB=6, JUMP=12
        if alu_op == 0:   # ld/sd → ADD
            return 2
        elif alu_op == 1: # beq → SUB
            return 6
        elif alu_op == 2: # R-type
            if funct3 == 0:
                return 6 if funct7 == 0x20 else 2  # sub vs add
            elif funct3 == 7: return 0  # and
            elif funct3 == 6: return 1  # or
            elif funct3 == 4: return 3  # xor
            elif funct3 == 3: return 3  # xor (alt encoding)
            elif funct3 == 2: return 6  # sub (alt)
        elif alu_op == 3: # jal → JUMP
            return 12
        return 0

    def _alu(self, a: int, b: int, ctrl: int) -> Tuple[int, int]:
        """ALU: compute result and zero flag."""
        if ctrl == 0:   # AND
            result = a & b
        elif ctrl == 1: # OR
            result = a | b
        elif ctrl == 2: # ADD
            result = (a + b) & 0xFF
        elif ctrl == 3: # XOR
            result = a ^ b
        elif ctrl == 4: # NOT
            result = (~a) & 0xFF
        elif ctrl == 6: # SUB
            result = (a - b) & 0xFF
        elif ctrl == 12: # JUMP
            result = 0
        else:
            result = 0
        zero = 1 if result == 0 else 0
        return result, zero

    def _imm_gen(self, inst: int) -> int:
        """Generate immediate from instruction."""
        opcode = inst & 0x7F
        op_hi3 = (opcode >> 4) & 0x7

        if op_hi3 == 0:  # 000_xxxx: I-type
            return (inst >> 20) & 0xFFF
        elif op_hi3 == 3:  # 011_xxxx: R-type
            return 0
        elif op_hi3 == 2:  # 010_xxxx: S-type
            funct7 = (inst >> 25) & 0x7F
            rd = (inst >> 7) & 0x1F
            return (funct7 << 5) | rd
        elif op_hi3 == 6:  # 110_xxxx
            if (opcode >> 3) & 1:  # 110_1xxx: UJ-type
                return (inst >> 20) & 0xFFF
            else:  # 110_0xxx: SB-type
                funct7 = (inst >> 25) & 0x7F
                rd = (inst >> 7) & 0x1F
                return (funct7 << 5) | rd
        return 0

    def _forward(self, rs: int, ex_mem_wr: int, ex_mem_rw: int,
                 mem_wb_wr: int, mem_wb_rw: int,
                 ex_mem_result: int, wb_data: int) -> int:
        """Forwarding logic for one register source."""
        if ex_mem_rw and ex_mem_wr != 0 and ex_mem_wr == rs:
            return ex_mem_result  # Forward from EX/MEM
        if mem_wb_rw and mem_wb_wr != 0 and mem_wb_wr == rs:
            return wb_data  # Forward from MEM/WB
        return None  # No forwarding needed

    def step(self) -> dict:
        """Execute one clock cycle. Returns state snapshot.

        Pipeline model (matching Verilog):
          Each cycle, each stage reads from the PREVIOUS stage's pipeline register
          (which was set at the end of the previous cycle), computes, and produces
          a new value for its OWN pipeline register.

          WB ← MEM_WB (previous cycle's MEM output)
          MEM ← EX_MEM (previous cycle's EX output)
          EX ← ID_EX (previous cycle's ID output)
          ID ← IF_ID (previous cycle's IF output)
          IF → inst_memory[PC] → IF_ID (capture current PC, then advance PC)
        """
        self.cycles += 1

        # ===== WB Stage: write result to register file =====
        wb_data = 0
        if self.MEM_WB.get("valid"):
            wb_data = (self.MEM_WB["read_data"] if self.MEM_WB["mem_to_reg"]
                       else self.MEM_WB["alu_result"])
            if self.MEM_WB["reg_write"] and self.MEM_WB["wr"] != 0:
                self.registers[self.MEM_WB["wr"]] = wb_data

        # ===== MEM Stage: data memory access + branch decision =====
        mem_to_reg_out = 0
        read_data = 0
        alu_result_out = 0
        reg_write_out = 0
        wr_out = 0
        pc_scr = 0
        branch_was_in_mem = False  # did MEM just process a taken branch?

        if self.EX_MEM.get("valid"):
            addr = self.EX_MEM["alu_result"] & (self.cfg.data_mem_size - 1)
            if self.EX_MEM["mem_write"]:
                self.data_memory[addr] = self.EX_MEM["write_data"] & 0xFF
            read_data = self.data_memory[addr] if self.EX_MEM["mem_read"] else 0

            # Branch decision (beq: branch & zero; jal: branch always, check alu_op=3→JUMP)
            pc_scr = self.EX_MEM["branch"] and self.EX_MEM["zero"]
            branch_was_in_mem = pc_scr

            mem_to_reg_out = self.EX_MEM["mem_to_reg"]
            alu_result_out = self.EX_MEM["alu_result"]
            reg_write_out = self.EX_MEM["reg_write"]
            wr_out = self.EX_MEM["wr"]

        # Store MEM_WB update (propagates EX_MEM → MEM_WB)
        mem_wb_update = {
            "mem_to_reg": mem_to_reg_out,
            "read_data": read_data,
            "alu_result": alu_result_out,
            "reg_write": reg_write_out,
            "wr": wr_out,
            "valid": self.EX_MEM.get("valid", False),
        }

        # ===== EX Stage: ALU + forwarding + operand mux =====
        ex_mem_update = {"valid": False, "branch": 0, "zero": 0}
        if self.ID_EX.get("valid") and not branch_was_in_mem:
            rs1_idx = (self.ID_EX.get("rs1", 0)) & (self.cfg.num_regs - 1)
            rs2_idx = (self.ID_EX.get("rs2", 0)) & (self.cfg.num_regs - 1)

            # Register read with forwarding
            alu_a = self.registers[rs1_idx]
            alu_b = self.registers[rs2_idx]

            # Forward from EX/MEM (highest priority)
            if (self.EX_MEM.get("reg_write") and self.EX_MEM.get("wr", 0) != 0
                and self.EX_MEM.get("wr") == rs1_idx):
                alu_a = self.EX_MEM.get("alu_result", 0)
            elif (self.MEM_WB.get("reg_write") and self.MEM_WB.get("wr", 0) != 0
                  and self.MEM_WB.get("wr") == rs1_idx):
                alu_a = wb_data

            if (self.EX_MEM.get("reg_write") and self.EX_MEM.get("wr", 0) != 0
                and self.EX_MEM.get("wr") == rs2_idx):
                alu_b = self.EX_MEM.get("alu_result", 0)
            elif (self.MEM_WB.get("reg_write") and self.MEM_WB.get("wr", 0) != 0
                  and self.MEM_WB.get("wr") == rs2_idx):
                alu_b = wb_data

            # ALU operand mux: alu_src ? immediate : reg2
            alu_op2 = self.ID_EX["imm"] if self.ID_EX["alu_src"] else alu_b

            # ALU control
            alu_ctrl = self._alu_control(
                self.ID_EX["alu_op"],
                (self.ID_EX["funct"] >> 3) & 0x7F,
                self.ID_EX["funct"] & 0x7
            )
            result, zero = self._alu(alu_a, alu_op2, alu_ctrl)

            ex_mem_update = {
                "valid": True,
                "branch": self.ID_EX["branch"],
                "mem_read": self.ID_EX["mem_read"],
                "mem_to_reg": self.ID_EX["mem_to_reg"],
                "mem_write": self.ID_EX["mem_write"],
                "alu_result": result,
                "write_data": alu_b,  # for sd: the value to store
                "zero": zero,
                "reg_write": self.ID_EX["reg_write"],
                "wr": self.ID_EX["wr"] & (self.cfg.num_regs - 1),
            }

        # ===== ID Stage: decode instruction, read register indices =====
        id_ex_update = {"valid": False}
        if self.IF_ID.get("valid") and not branch_was_in_mem:
            inst = self.IF_ID["inst"]
            if inst != 0:  # NOP = all zeros
                decoded = self._decode_instruction(inst)
                ctrl = self._control(decoded["opcode"])
                imm = self._imm_gen(inst)
                funct = (decoded["funct7"] << 3) | decoded["funct3"]

                id_ex_update = {
                    "valid": True,
                    "inst_raw": inst,
                    "pc": self.IF_ID["pc"],
                    "data1": 0,  # register read happens in EX via forwarding
                    "data2": 0,
                    "imm": imm,
                    "funct": funct,
                    "rs1": decoded["rs1"],
                    "rs2": decoded["rs2"],
                    "branch": ctrl["branch"],
                    "mem_read": ctrl["mem_read"],
                    "mem_to_reg": ctrl["mem_to_reg"],
                    "alu_op": ctrl["alu_op"],
                    "mem_write": ctrl["mem_write"],
                    "alu_src": ctrl["alu_src"],
                    "reg_write": ctrl["reg_write"],
                    "wr": decoded["rd"],
                }
                self.total_instructions += 1

        # ===== IF Stage: fetch instruction at CURRENT PC, then advance =====
        # CRITICAL: Capture inst_memory[CURRENT_PC] into IF_ID, THEN advance PC.
        # The advance is for the NEXT cycle's fetch.
        mask = (1 << self.cfg.pc_size) - 1

        if branch_was_in_mem:
            # Branch taken (pc_scr from MEM): flush pipeline, jump to target
            # Jump target = ID_EX.pc + ID_EX.imm (computed in EX and propagated)
            # The EX stage already computed it: EX_MEM.alu_result for jal,
            # or for beq: the address was already computed in EX
            # Actually: PC_jump = PC_ID_EX + immediate (from ID/EX)
            # But we need the original PC from when the branch was in ID...
            # For beq: jump to PC + imm (where imm is the branch offset)
            # For jal: jump to PC + imm
            # Since we captured ID_EX.pc before the branch entered EX:
            branch_pc = self.ID_EX.get("pc", self.PC)
            branch_imm = self.ID_EX.get("imm", 0)
            jump_target = (branch_pc + branch_imm) & mask
            self.PC = jump_target
            # Flush: ID_EX already invalidated (branch_was_in_mem skips EX)
        else:
            # Normal fetch: capture current PC, then advance
            current_pc = self.PC
            if current_pc < self.cfg.inst_mem_size:
                if_id_update = {
                    "pc": current_pc,
                    "inst": self.inst_memory[current_pc],
                    "valid": True
                }
            else:
                if_id_update = {"pc": current_pc, "inst": 0, "valid": False}
            # Advance PC for NEXT cycle
            self.PC = (current_pc + 1) & mask

        # On branch taken, flush IF_ID (instruction after branch is wrong)
        if branch_was_in_mem:
            if_id_update = {"pc": self.PC, "inst": self.inst_memory[self.PC], "valid": True}

        # ===== Update all pipeline registers =====
        self.MEM_WB = mem_wb_update
        self.EX_MEM = ex_mem_update
        self.ID_EX = id_ex_update
        self.IF_ID = if_id_update

        return {
            "cycle": self.cycles,
            "PC": self.PC,
            "IF_ID_inst": f"0x{self.IF_ID['inst']:08X}" if self.IF_ID.get("valid") else "NOP",
            "ID_EX_inst": f"0x{self.ID_EX.get('inst_raw', 0):08X}" if self.ID_EX.get("valid") else "NOP",
            "EX_MEM_valid": self.EX_MEM.get("valid", False),
            "MEM_WB_wr": self.MEM_WB.get("wr", 0),
            "MEM_WB_data": wb_data,
            "regs": list(self.registers[:self.cfg.num_regs]),
            "branch_taken": branch_was_in_mem,
        }

    def run(self, max_cycles: int = 100, trace: bool = False) -> List[dict]:
        """Run simulation for max_cycles."""
        trace_log = []
        for _ in range(max_cycles):
            state = self.step()
            if trace:
                trace_log.append(state)
            # Check if pipeline is drained
            if (not self.IF_ID.get("valid") and not self.ID_EX.get("valid")
                and not self.EX_MEM.get("valid") and not self.MEM_WB.get("valid")
                and self.cycles > 10):
                break
        return trace_log if trace else trace_log[-1:]  # return last state if no trace


# ============================================================
# Step 4: Compile to Redstone Build JSON
# ============================================================

def compile_to_build_json(compiler: RISCVRTL, cpu: Module,
                          origin: Tuple[int, int, int] = (0, 0, 0)) -> dict:
    """Flatten the module hierarchy into a single block list for /setblock building.

    Places each module in a designated region of the build area:
      - IF: west end
      - ID: next
      - EXE: center
      - MEM: next
      - WB: east end
      Pipeline registers: between stages
    """
    bx, by, bz = origin
    all_blocks = []

    # Layout plan (approximate, will be refined by placer)
    # Each stage gets a column ~50 blocks wide, ~20 blocks deep
    STAGE_WIDTH = 60
    STAGE_DEPTH = 30
    STAGE_GAP = 10  # gap between stages

    stage_positions = {
        "IF":  (bx, by, bz),
        "ID":  (bx + STAGE_WIDTH + STAGE_GAP, by, bz),
        "EXE": (bx + 2 * (STAGE_WIDTH + STAGE_GAP), by, bz),
        "MEM": (bx + 3 * (STAGE_WIDTH + STAGE_GAP), by, bz),
        "WB":  (bx + 4 * (STAGE_WIDTH + STAGE_GAP), by, bz),
    }

    def place_module(mod: Module, ox: int, oy: int, oz: int, label: str = ""):
        """Place all cells in a module at absolute coordinates."""
        x_offset = 0
        y_offset = 0
        z_offset = 0
        ROW_SIZE = 10  # cells per row before wrapping

        for i, (cell_name, cell) in enumerate(mod.cells.items()):
            gt = cell.gtype.value
            layout = GATE_LAYOUTS.get(gt, [])
            if not layout:
                continue

            # Calculate position within stage
            col = i % ROW_SIZE
            row = i // ROW_SIZE
            cell_x = ox + x_offset + col * 8  # 8-block spacing between cells
            cell_y = oy + y_offset + row * 4
            cell_z = oz + z_offset

            for block in layout:
                px, py, pz = block["pos"]
                all_blocks.append({
                    "pos": [cell_x + px, cell_y + py, cell_z + pz],
                    "block": block["block"],
                    "role": block["role"],
                    "cell": cell_name,
                    "gate_type": gt,
                    "module": mod.name,
                    "stage": label,
                })

    # Place each stage
    stage_modules = {
        "IF": ["Instruction_Memory", "IF_ID"],
        "ID": ["Control", "Registers", "Imm_Gen", "ID_EX"],
        "EXE": ["ALU", "ALU_Control", "Forwarding_Unit", "EX_MEM"],
        "MEM": ["Data_Memory", "MEM_WB"],
        "WB": [],
    }

    for stage, mod_names in stage_modules.items():
        ox, oy, oz = stage_positions[stage]
        for name in mod_names:
            if name in cpu.submodules:
                place_module(cpu.submodules[name], ox, oy, oz, stage)

    # Compute dimensions
    max_x = max((b["pos"][0] for b in all_blocks), default=0)
    max_y = max((b["pos"][1] for b in all_blocks), default=0)
    max_z = max((b["pos"][2] for b in all_blocks), default=0)

    return {
        "name": "RISCV_8bit_Pipeline_CPU",
        "category": "cpu",
        "architecture": "RISC-V RV32I subset, 5-stage pipeline",
        "dimensions": {
            "width": max_x - bx + 10,
            "height": max_y - by + 5,
            "depth": max_z - bz + 10,
        },
        "origin": list(origin),
        "total_blocks": len(all_blocks),
        "estimated_blocks": compiler.estimate_blocks(cpu),
        "propagation_delay_ticks": compiler.estimate_delay(cpu),
        "cells_by_type": compiler.count_cells(cpu),
        "instructions": ["ld", "sd", "beq", "add", "sub", "and", "or", "xor", "not", "jal", "nop"],
        "pipeline_stages": ["IF", "ID", "EXE", "MEM", "WB"],
        "blocks": all_blocks,
    }


# ============================================================
# Main: Demo compilation
# ============================================================

def main():
    print("=" * 70)
    print("  RISC-V 8-bit Pipeline CPU → Redstone Compiler")
    print("  Source: ujjwal-2001/RISCV_8bit_pipeline (IISc Bangalore)")
    print("=" * 70)

    # Scale configuration
    configs = [
        ("Tiny (demo)", CPUConfig(num_regs=4, data_mem_size=16, inst_mem_size=8, pc_size=3)),
        ("Small (practical)", CPUConfig(num_regs=8, data_mem_size=32, inst_mem_size=16, pc_size=4)),
        ("Full (theoretical)", CPUConfig(num_regs=32, data_mem_size=256, inst_mem_size=64, pc_size=6)),
    ]

    for label, cfg in configs:
        print(f"\n{'─' * 60}")
        print(f"  Configuration: {label}")
        print(f"    Registers: {cfg.num_regs} × 8-bit")
        print(f"    Data Memory: {cfg.data_mem_size} bytes")
        print(f"    Instruction Memory: {cfg.inst_mem_size} × 32-bit words")
        print(f"    PC: {cfg.pc_size}-bit")

        compiler = RISCVRTL(cfg)
        cpu = compiler.build_cpu()

        # Stats
        counts = compiler.count_cells(cpu)
        est_blocks = compiler.estimate_blocks(cpu)
        delay = compiler.estimate_delay(cpu)

        print(f"\n  Gate-Level Statistics:")
        print(f"    Total cells: {sum(counts.values())}")
        print(f"    By type: {dict(sorted(counts.items(), key=lambda x: -x[1]))}")
        print(f"    Estimated Minecraft blocks: {est_blocks:,}")
        print(f"    Estimated critical path: {delay} rt")

        submodule_counts = {}
        for name, sub in cpu.submodules.items():
            submodule_counts[name] = sum(
                compiler.count_cells(sub, recurse=False).values()
            )
        print(f"    Submodule cells: {submodule_counts}")

        # Build JSON
        build_json = compile_to_build_json(compiler, cpu)
        print(f"\n  Build JSON: {len(json.dumps(build_json)):,} chars")
        print(f"    Build dimensions: {build_json['dimensions']}")
        print(f"    Total blocks in layout: {build_json['total_blocks']}")

    # ---- Simulation Demo ----
    print(f"\n{'=' * 70}")
    print("  Simulation: Testbench Program (from TOP_tb.v)")
    print("=" * 70)

    # Use tiny config for simulation demo
    cfg = CPUConfig(num_regs=8, data_mem_size=16, inst_mem_size=16, pc_size=4)
    sim = RISCVRTLSimulator(cfg)

    # Program from the Verilog testbench (parity toggle):
    # ld r1, 0(r5)  — r5=0 (base), r1 = MEM[0] = 1
    # ld r2, 0(r6)  — r6=1, r2 = MEM[1] = 6
    # ld r3, 0(r1)  — r3 = MEM[1] = 6 (r1=1 after first ld... actually let's simplify)

    # Simplified test: ADD r1, r2, r3 → result in r1
    # R-type ADD: funct7=0000000, rs2=r3, rs1=r2, funct3=000, rd=r1, opcode=0110011
    # = 0000000_00011_00010_000_00001_0110011

    # Let's write a real test program matching the original testbench intent:
    test_program = [
        # 0: ld r1, 0(r0)  — r1 = MEM[0] = 5
        # I-type: imm[11:0]=0, rs1=r0=0, funct3=000, rd=r1=1, opcode=0000011
        0b000000000000_00000_000_00001_0000011,
        # 1: ld r2, 1(r0)  — r2 = MEM[1] = 3
        # I-type: imm[11:0]=1, rs1=r0=0, funct3=000, rd=r2=2, opcode=0000011
        0b000000000001_00000_000_00010_0000011,
        # 2: nop (pipeline fill)
        0x00000000,
        # 3: nop
        0x00000000,
        # 4: add r3, r1, r2  — r3 = r1 + r2 = 5+3 = 8
        # R-type: funct7=0000000, rs2=r2=2, rs1=r1=1, funct3=000, rd=r3=3, opcode=0110011
        0b0000000_00010_00001_000_00011_0110011,
        # 5: nop
        0x00000000,
        # 6: nop
        0x00000000,
        # 7: sub r4, r3, r2  — r4 = r3 - r2 = 8-3 = 5
        # R-type: funct7=0100000, rs2=r2=2, rs1=r3=3, funct3=000, rd=r4=4, opcode=0110011
        0b0100000_00010_00011_000_00100_0110011,
        # 8: nop
        0x00000000,
        # 9: nop
        0x00000000,
        # 10: and r5, r1, r2  — r5 = r1 & r2 = 5&3 = 1
        # R-type: funct7=0000000, rs2=r2=2, rs1=r1=1, funct3=111, rd=r5=5, opcode=0110011
        0b0000000_00010_00001_111_00101_0110011,
        # 11: nop
        0x00000000,
        # 12: or r6, r1, r2  — r6 = r1 | r2 = 5|3 = 7
        # R-type: funct7=0000000, rs2=r2=2, rs1=r1=1, funct3=110, rd=r6=6, opcode=0110011
        0b0000000_00010_00001_110_00110_0110011,
        # 13: nop
        0x00000000,
        # 14: xor r7, r1, r2  — r7 = r1 ^ r2 = 5^3 = 6
        # R-type: funct7=0000000, rs2=r2=2, rs1=r1=1, funct3=100, rd=r7=7, opcode=0110011
        0b0000000_00010_00001_100_00111_0110011,
        # 15: nop
        0x00000000,
    ]

    test_data = [5, 3, 10, 11, 14, 4, 8, 0]  # MEM[0]=5, MEM[1]=3

    sim.load_program(test_program, test_data)
    print(f"\n  Program loaded: {len(test_program)} instructions")
    print(f"  Data: {test_data}")

    # Run
    trace = sim.run(max_cycles=40, trace=True)
    print(f"\n  Simulation complete: {sim.cycles} cycles, {sim.total_instructions} instructions")
    print(f"  Final PC: {sim.PC}")
    print(f"  Registers: {sim.registers[:8]}")

    # Verify expected results
    print(f"\n  Results:")
    print(f"    r1 (MEM[0])    = {sim.registers[1]} (expected: 5) {'✅' if sim.registers[1] == 5 else '❌'}")
    print(f"    r2 (MEM[1])    = {sim.registers[2]} (expected: 3) {'✅' if sim.registers[2] == 3 else '❌'}")
    print(f"    r3 (r1+r2)     = {sim.registers[3]} (expected: 8) {'✅' if sim.registers[3] == 8 else '❌'}")
    print(f"    r4 (r3-r2)     = {sim.registers[4]} (expected: 5) {'✅' if sim.registers[4] == 5 else '❌'}")
    print(f"    r5 (r1&r2)     = {sim.registers[5]} (expected: {5&3}) {'✅' if sim.registers[5] == (5&3) else '❌'}")
    print(f"    r6 (r1|r2)     = {sim.registers[6]} (expected: {5|3}) {'✅' if sim.registers[6] == (5|3) else '❌'}")
    print(f"    r7 (r1^r2)     = {sim.registers[7]} (expected: {5^3}) {'✅' if sim.registers[7] == (5^3) else '❌'}")

    # Pipeline trace
    print(f"\n  Pipeline Trace (first 15 cycles):")
    print(f"  {'Cycle':>6} {'PC':>4} {'IF/ID':>12} {'Status':>20}")
    for t in trace[:15]:
        pc = t.get("PC", 0)
        inst = t.get("IF_ID_inst", "NOP")
        wb = t.get("MEM_WB_wr", 0)
        wd = t.get("MEM_WB_data", 0)
        print(f"  {t['cycle']:>6} {pc:>4} {inst:>12} {'WB: r'+str(wb)+'='+str(wd):>20}")

    # Compilation summary for build
    compiler = RISCVRTL(cfg)
    cpu = compiler.build_cpu()
    counts = compiler.count_cells(cpu)
    est_blocks = compiler.estimate_blocks(cpu)

    print(f"\n{'=' * 70}")
    print(f"  Redstone Compilation Summary ({cfg.num_regs} regs, {cfg.inst_mem_size} insts)")
    print(f"  Total gates: {sum(counts.values()):,}")
    print(f"  Estimated blocks: {est_blocks:,}")
    print(f"  Critical path: {compiler.estimate_delay(cpu)} rt")
    print(f"  Pipeline: IF({compiler.estimate_delay(cpu.submodules.get('Instruction_Memory', cpu))}rt)"
          f" → ID → EXE({compiler.estimate_delay(cpu.submodules.get('ALU', cpu))}rt)"
          f" → MEM → WB")
    print(f"{'=' * 70}")

    # Save build JSON
    build_json = compile_to_build_json(compiler, cpu)
    out_path = os.path.join(os.path.dirname(__file__), "riscv_cpu_build.json")
    with open(out_path, 'w') as f:
        json.dump(build_json, f, indent=2)
    print(f"\nBuild JSON saved to: {out_path}")
    print(f"  ({len(json.dumps(build_json)):,} chars, {build_json['total_blocks']} blocks in layout)")

    return build_json


if __name__ == '__main__':
    main()
