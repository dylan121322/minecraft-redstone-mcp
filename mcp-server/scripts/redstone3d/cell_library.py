"""
cell_library.py — Standardized 3D redstone gate cells (MCHPRS-verified).

Each cell has a UNIFORM pin interface so the router can connect cells:
  - Inputs enter on the WEST face (local x=0), at fixed local z per pin.
  - Outputs exit on the EAST face (local x=W-1), at fixed local z per pin.
  - All pins at local y=0. Cell logic occupies y=0 (wires/mounts) and y=1 (torch tips).
  - Cell bounding box: (width, height, depth) in +x/+y/+z from the cell origin.

A cell is placed by calling cell.emit(schem, ox, oy, oz), which writes blocks
at absolute coords (ox+lx, oy+ly, oz+lz). The floor (y=-1) is placed by the
placer, not the cell, so cells can share a common substrate.

Pin coordinates are LOCAL (relative to cell origin). The router maps them to
absolute coords after placement.

Verified in MCHPRS (see mchprs_sim):
  NOT 2/2, AND 4/4, OR 4/4, BUF (wire), NAND (AND+NOT).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Callable
import nucleation as nuc

LPos = Tuple[int, int, int]  # local position


@dataclass
class Cell:
    gtype: str
    width: int                       # x extent
    height: int                      # y extent (logic layers)
    depth: int                       # z extent
    inputs: Dict[str, LPos]          # pin name -> local (x,y,z), on west face
    outputs: Dict[str, LPos]         # pin name -> local (x,y,z), on east face
    _emit: Callable[[nuc.Schematic, int, int, int], None]

    def emit(self, schem: nuc.Schematic, ox: int, oy: int, oz: int) -> None:
        self._emit(schem, ox, oy, oz)

    def input_abs(self, name: str, ox: int, oy: int, oz: int) -> LPos:
        lx, ly, lz = self.inputs[name]
        return (ox + lx, oy + ly, oz + lz)

    def output_abs(self, name: str, ox: int, oy: int, oz: int) -> LPos:
        lx, ly, lz = self.outputs[name]
        return (ox + lx, oy + ly, oz + lz)


def _wt(facing="east"):
    return f"minecraft:redstone_wall_torch[facing={facing}]"

W = "minecraft:redstone_wire"
S = "minecraft:stone"
TARGET = "minecraft:target"
def _repw():
    return "minecraft:repeater[facing=west,delay=1]"


def _target_stage(B, qx, qy, qz):
    """Append the TARGET output stage at (qx+1..qx+3): repeater reads the classic
    Q dust, drives a target, the net reads the target's output dust at qx+3.
    The target makes the output readable but not back-drivable — a downstream
    net can never force this gate's output, and a stray wire near the output
    cannot couple into the gate. Verified 4/4 on all cells
    (riscv_build/test_cell_target_stage.py)."""
    B(qx + 1, qy, qz, _repw())
    B(qx + 2, qy, qz, TARGET)
    B(qx + 3, qy, qz, W)


# ---------------------------------------------------------------------------
# NOT: input wire -> stone -> wall_torch -> output wire.  3 wide, verified 2/2.
#   in  @ (0,0,0)   out @ (3,0,0)
# ---------------------------------------------------------------------------
# Input pin is a REPEATER (facing=west, in from west). It strongly powers the
# mount regardless of how the routed signal arrived (side-entry safe), fixing
# the STRONG_POWER_STRAIGHT limitation when wires turn into a pin.
REP_W = "minecraft:repeater[facing=west,delay=1]"

def _emit_not(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)      # input pin (repeater)
    B(1, 0, 0, S)          # mount
    B(2, 0, 0, _wt())      # wall torch (inverts)
    B(3, 0, 0, W)          # internal output
    _target_stage(B, 3, 0, 0)   # repeater->target->Q at (4..6)

NOT = Cell("NOT", 7, 2, 1, {"A": (0, 0, 0)}, {"Q": (6, 0, 0)}, _emit_not)


# ---------------------------------------------------------------------------
# BUF: input wire -> repeater -> output wire.  Isolates/refreshes signal.
#   in @ (0,0,0)  out @ (2,0,0)
# ---------------------------------------------------------------------------
def _emit_buf(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, W)
    B(1, 0, 0, "minecraft:repeater[facing=west,delay=1]")  # facing=west: input from west
    B(2, 0, 0, W)
    _target_stage(B, 2, 0, 0)

BUF = Cell("BUF", 6, 1, 1, {"A": (0, 0, 0)}, {"Q": (5, 0, 0)}, _emit_buf)


# ---------------------------------------------------------------------------
# OR: two inputs at z=0 and z=2, wire junction, output at z=1. verified 4/4.
#   A @ (0,0,0)  B @ (0,0,2)  Q @ (2,0,1)
# ---------------------------------------------------------------------------
def _emit_or(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W); B(0, 0, 2, REP_W)  # inputs as repeaters (side-entry safe, isolate)
    B(1, 0, 0, W); B(1, 0, 2, W)
    B(1, 0, 1, W)      # junction column
    B(2, 0, 1, W)
    _target_stage(B, 2, 0, 1)

OR = Cell("OR", 6, 1, 3, {"A": (0, 0, 0), "B": (0, 0, 2)}, {"Q": (5, 0, 1)}, _emit_or)


# ---------------------------------------------------------------------------
# AND = NOT(A) NOR NOT(B) via double inversion. verified 4/4.
#   A @ (0,0,0)  B @ (0,0,2)  Q @ (7,0,1)
#   Layout (all y=0): NOT-A, NOT-B (wall torches) -> merge wires -> straight
#   seg -> final NOT -> output. Straight seg is REQUIRED for strong power.
# ---------------------------------------------------------------------------
def _emit_and(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W); B(0, 0, 2, REP_W)         # inputs (repeaters, side-entry safe)
    B(1, 0, 0, S); B(2, 0, 0, _wt())             # NOT A
    B(1, 0, 2, S); B(2, 0, 2, _wt())             # NOT B
    B(3, 0, 0, W); B(3, 0, 2, W); B(3, 0, 1, W)  # merge
    B(4, 0, 1, W)                                # straight segment (strong power)
    B(5, 0, 1, S); B(6, 0, 1, _wt())             # final NOT
    B(7, 0, 1, W)                                # output
    _target_stage(B, 7, 0, 1)

AND = Cell("AND", 11, 2, 3, {"A": (0, 0, 0), "B": (0, 0, 2)}, {"Q": (10, 0, 1)}, _emit_and)


# ---------------------------------------------------------------------------
# NAND = AND then NOT. Extend AND with one more inverter.
#   A @ (0,0,0)  B @ (0,0,2)  Q @ (10,0,1)
# ---------------------------------------------------------------------------
def _emit_nand(schem, ox, oy, oz):
    # standalone NAND (does NOT reuse _emit_and, which has its own target stage):
    # AND core + extra NOT + target stage. Q at (13,0,1).
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W); B(0, 0, 2, REP_W)
    B(1, 0, 0, S); B(2, 0, 0, _wt())
    B(1, 0, 2, S); B(2, 0, 2, _wt())
    B(3, 0, 0, W); B(3, 0, 2, W); B(3, 0, 1, W)
    B(4, 0, 1, W)
    B(5, 0, 1, S); B(6, 0, 1, _wt())
    B(7, 0, 1, W)                                # AND output
    B(8, 0, 1, S); B(9, 0, 1, _wt())             # extra NOT
    B(10, 0, 1, W)                               # NAND output (pre-stage)
    _target_stage(B, 10, 0, 1)

NAND = Cell("NAND", 14, 2, 3, {"A": (0, 0, 0), "B": (0, 0, 2)}, {"Q": (13, 0, 1)}, _emit_nand)


# ---------------------------------------------------------------------------
# NOR = OR then NOT.
#   A @ (0,0,0)  B @ (0,0,2)  Q @ (5,0,1)
# ---------------------------------------------------------------------------
def _emit_nor(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W); B(0, 0, 2, REP_W)         # inputs as repeaters
    B(1, 0, 0, W); B(1, 0, 2, W)
    B(1, 0, 1, W); B(2, 0, 1, W)                 # OR junction + straight seg
    B(3, 0, 1, S); B(4, 0, 1, _wt())             # NOT
    B(5, 0, 1, W)                                # output
    _target_stage(B, 5, 0, 1)

NOR = Cell("NOR", 9, 2, 3, {"A": (0, 0, 0), "B": (0, 0, 2)}, {"Q": (8, 0, 1)}, _emit_nor)


LIBRARY = {c.gtype: c for c in [NOT, BUF, OR, AND, NAND, NOR]}


def get(gtype: str) -> Cell:
    if gtype not in LIBRARY:
        raise KeyError(f"no cell for gate {gtype!r}; have {list(LIBRARY)}")
    return LIBRARY[gtype]


# ---------------------------------------------------------------------------
# Self-verification: run every cell's truth table through MCHPRS.
# ---------------------------------------------------------------------------
def verify_all(verbose=True):
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from mchprs_sim import simulate_vectors, set_input_block, report

    truth = {
        "NOT":  (["A"],      lambda A: 1 - A),
        "BUF":  (["A"],      lambda A: A),
        "OR":   (["A", "B"], lambda A, B: A | B),
        "AND":  (["A", "B"], lambda A, B: A & B),
        "NAND": (["A", "B"], lambda A, B: 1 - (A & B)),
        "NOR":  (["A", "B"], lambda A, B: 1 - (A | B)),
    }
    ox, oy, oz = 5, 5, 5
    all_ok = True
    for gtype, (ins, fn) in truth.items():
        cell = get(gtype)

        def build(schem, inputs, _cell=cell, _ins=ins):
            # floor spanning the cell + input stubs
            for dx in range(-3, _cell.width + 2):
                for dz in range(-1, _cell.depth + 1):
                    schem.set_block_from_string(ox+dx, oy-1, oz+dz, "minecraft:stone")
            # place cell
            _cell.emit(schem, ox, oy, oz)
            # inject inputs: redstone_block one block WEST of each input pin
            for name in _ins:
                px, py, pz = _cell.inputs[name]
                set_input_block(schem, (ox+px-1, oy+py, oz+pz), inputs.get(name, 0))

        # test vectors
        combos = [(0,), (1,)] if len(ins) == 1 else [(a, b) for a in (0, 1) for b in (0, 1)]
        tvs = []
        for c in combos:
            ivals = dict(zip(ins, c))
            tvs.append({"inputs": ivals, "expected": {"Q": fn(*c)}})

        out_pin = cell.outputs["Q"]
        probe = (ox + out_pin[0], oy + out_pin[1], oz + out_pin[2])
        res = simulate_vectors(build, ins, {"Q": probe}, tvs, ticks=10, lamp_outputs=False)
        ok = report(gtype, res) if verbose else all(r["match"] for r in res)
        all_ok = all_ok and ok
    return all_ok


if __name__ == "__main__":
    ok = verify_all()
    print("\nALL CELLS VERIFIED" if ok else "\nSOME CELLS FAILED")
