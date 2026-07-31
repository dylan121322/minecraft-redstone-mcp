"""
reserve.py — protected regions for multi-cell gadgets, with automatic overwrite
detection.

The problem this solves: a delivery gadget (down tower + dust lead + inverter +
run) has ~8 cells whose contents are each semantically load-bearing — this cell
MUST hold a wall torch, that one MUST hold dust. Nothing was protecting them, so
the per-zone local routing, the floor slab, the cell library and other nets could
all silently write over them. Every such collision changed the polarity or cut the
link, and the only way to find one was to route, measure, guess, move, repeat.
That is whack-a-mole, not convergence.

The mechanism:
  * a gadget registers a Reservation: the exact (x,y,z) -> blockstate it expects;
  * anything that emits blocks goes through `guarded_setter`, which records
    attempted writes into reserved cells instead of letting them pass silently;
  * after emit, `audit` compares expectations against reality and reports every
    mismatch with the offending value, so a break is located instead of hunted.

Nothing here is module-specific; the same mechanism will serve the sequential
gadgets (flip-flops, register files) that come later and are much larger.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

Pos = Tuple[int, int, int]


@dataclass
class Reservation:
    """One gadget's claim: every cell it owns and the blockstate it must hold."""
    owner: str                       # e.g. "n4:sink0:down_tower"
    expect: Dict[Pos, str]           # cell -> required blockstate
    note: str = ""

    def cells(self):
        return self.expect.keys()


@dataclass
class Violation:
    cell: Pos
    owner: str
    expected: str
    actual: Optional[str]
    writer: str                      # who tried to write it

    def __str__(self):
        return (f"{self.cell} owned by {self.owner}: expected "
                f"{self.expected.replace('minecraft:', '')}, got "
                f"{str(self.actual).replace('minecraft:', '')}"
                f" (written by {self.writer})")


class ReserveMap:
    def __init__(self):
        self.by_cell: Dict[Pos, Tuple[str, str]] = {}   # cell -> (owner, expected)
        self.reservations: List[Reservation] = []
        self.attempts: List[Tuple[Pos, str, str]] = []  # (cell, value, writer)

    # ---------- registration ----------
    def reserve(self, res: Reservation) -> List[Pos]:
        """Claim cells. Returns any cells already claimed by a DIFFERENT owner —
        a planning-time conflict, which is far cheaper to handle than an emit-time
        overwrite."""
        clashes = []
        for cell, want in res.expect.items():
            prev = self.by_cell.get(cell)
            if prev is not None and prev[0] != res.owner:
                clashes.append(cell)
                continue
            self.by_cell[cell] = (res.owner, want)
        self.reservations.append(res)
        return clashes

    def free(self, cell: Pos) -> bool:
        return cell not in self.by_cell

    def owner_of(self, cell: Pos) -> Optional[str]:
        e = self.by_cell.get(cell)
        return e[0] if e else None

    # ---------- guarded emission ----------
    def guarded_setter(self, inner, writer: str):
        """Wrap a set_block-style callable so writes into reserved cells that do
        not match the reservation are recorded and DROPPED rather than silently
        corrupting the gadget."""
        def setter(x, y, z, s):
            cell = (int(x), int(y), int(z))
            e = self.by_cell.get(cell)
            if e is not None and e[0] != writer and s != e[1]:
                self.attempts.append((cell, s, writer))
                return                        # protect the gadget
            inner(x, y, z, s)
        return setter

    # ---------- verification ----------
    def audit(self, blocks: Dict[Pos, str]) -> List[Violation]:
        """Compare every reserved cell against what actually got emitted."""
        out = []
        writers = {}
        for (cell, val, who) in self.attempts:
            writers.setdefault(cell, []).append(f"{who}->{val.split(':')[-1]}")
        for cell, (owner, want) in self.by_cell.items():
            got = blocks.get(cell)
            if got != want:
                out.append(Violation(cell, owner, want, got,
                                     ",".join(writers.get(cell, ["?"]))))
        return out

    def summary(self) -> dict:
        return {"reservations": len(self.reservations),
                "reserved_cells": len(self.by_cell),
                "blocked_writes": len(self.attempts)}


def reservation_from_cells(owner: str, cells, note: str = "") -> Reservation:
    """Build a Reservation from a gadget's (x, y, z, blockstate) output."""
    return Reservation(owner, {(x, y, z): b for (x, y, z, b) in cells}, note)
