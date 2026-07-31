"""
signal_protocol.py — a link-layer protocol for redstone segments.

Why a protocol. The global delivery path has five segments (source tower, trunk
run, column leg, delivery box, feed run) and every boundary between them was hand
reasoned: which cell touches which, how much signal strength survives, which way a
repeater faces, which Y plane it lives on. Nothing checked those assumptions, so a
change in one segment quietly broke a neighbour, and each debugging round removed
one class of fault only to expose the next.

So segments now negotiate like network layers do. Every segment declares a PORT at
each end:

    Port(cell, plane, kind, level, direction)

      cell      the exact (x, y, z) that carries the signal at this boundary
      plane     which Y layer the segment lives on (planes must match or the
                boundary must be an explicit riser)
      kind      what physically sits there: DUST / REPEATER_OUT / TORCH_OUT /
                BLOCK  — because a repeater output cannot feed another repeater's
                back, and a torch output cannot be read as dust
      level     guaranteed signal strength AT that cell (0-15). A downstream
                segment states the minimum it needs; the check catches decay
                before it is measured in a world.
      polarity  NORMAL or INVERTED, so double inversions are caught by arithmetic
                instead of by reading a lamp

`Link.check` compares an upstream OUT port with a downstream IN port and returns
the concrete violations. `Chain.validate` walks a whole path and reports the first
boundary that cannot hold, with the reason.

This is deliberately independent of the geometry helpers: a segment only has to
describe its ports honestly, and the arithmetic does the rest.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

Pos = Tuple[int, int, int]


class Kind(Enum):
    DUST = "dust"                 # plain redstone dust, readable by anything
    REPEATER_OUT = "repeater_out"  # a repeater's output side: strong, directional
    TORCH_OUT = "torch_out"        # a torch's output: strong, inverted already
    BLOCK = "block"                # a solid block used as a power carrier


class Polarity(Enum):
    NORMAL = 1
    INVERTED = -1

    def __mul__(self, other: "Polarity") -> "Polarity":
        return Polarity(self.value * other.value)


@dataclass(frozen=True)
class Port:
    cell: Pos
    plane: int                    # the Y this segment operates on
    kind: Kind
    level: int                    # guaranteed strength at `cell` (0..15)
    polarity: Polarity = Polarity.NORMAL
    facing: Optional[str] = None  # for directional kinds

    def describe(self) -> str:
        return (f"{self.cell} plane={self.plane} {self.kind.value} "
                f"level={self.level} {self.polarity.name}"
                + (f" facing={self.facing}" if self.facing else ""))


@dataclass
class Segment:
    """One physical piece of the path, described by its two ports."""
    name: str
    in_port: Port
    out_port: Port
    needs_level: int = 1          # minimum level it must receive to work
    blocks: dict = field(default_factory=dict)

    def describe(self) -> str:
        return (f"{self.name}: in {self.in_port.describe()} -> "
                f"out {self.out_port.describe()} (needs >= {self.needs_level})")


@dataclass
class Violation:
    boundary: str
    reason: str

    def __str__(self):
        return f"{self.boundary}: {self.reason}"


class Link:
    """Checks one boundary: upstream.out must be able to feed downstream.in."""

    @staticmethod
    def check(up: Segment, down: Segment) -> List[Violation]:
        b = f"{up.name} -> {down.name}"
        out, inp = up.out_port, down.in_port
        v: List[Violation] = []

        # 1. the two segments must actually touch
        if out.cell != inp.cell:
            dist = sum(abs(a - c) for a, c in zip(out.cell, inp.cell))
            if dist > 1:
                v.append(Violation(b, f"cells not adjacent: {out.cell} vs "
                                      f"{inp.cell} (manhattan {dist})"))

        # 2. planes must agree unless one side declares a riser
        if out.plane != inp.plane and out.kind is not Kind.BLOCK:
            v.append(Violation(b, f"plane mismatch: {out.plane} vs {inp.plane} "
                                  f"(needs an explicit riser segment)"))

        # 3. strength must survive
        if out.level < down.needs_level:
            v.append(Violation(b, f"level {out.level} below the "
                                  f"{down.needs_level} {down.name} needs "
                                  f"(insert a repeater upstream)"))

        # 4. a repeater cannot be fed from its own output side
        if out.kind is Kind.REPEATER_OUT and inp.kind is Kind.REPEATER_OUT:
            v.append(Violation(b, "repeater output driving a repeater output"))

        # 5. a BLOCK carries power only if something STRONGLY powers it. Dust lying
        #    next to a block does not energise it enough to switch a torch, so a
        #    block input needs a repeater (or a torch) aimed at it. This dimension
        #    was missing while the protocol still reported chains as valid that
        #    MCHPRS measured dead: the declarations were honest, the rule set was
        #    incomplete.
        if inp.kind is Kind.BLOCK and out.kind not in (Kind.REPEATER_OUT,
                                                       Kind.TORCH_OUT):
            v.append(Violation(b, f"{down.name} input is a solid block but "
                                  f"{up.name} ends in {out.kind.value}; a block "
                                  f"needs a repeater or torch driving it"))

        return v


class Chain:
    """A whole path. Validates every boundary and the end-to-end polarity."""

    def __init__(self, name: str):
        self.name = name
        self.segments: List[Segment] = []

    def add(self, seg: Segment) -> "Chain":
        self.segments.append(seg)
        return self

    def polarity(self) -> Polarity:
        p = Polarity.NORMAL
        for s in self.segments:
            p = p * s.out_port.polarity
        return p

    def validate(self, want: Polarity = Polarity.NORMAL) -> List[Violation]:
        out: List[Violation] = []
        for a, b in zip(self.segments, self.segments[1:]):
            out.extend(Link.check(a, b))
        got = self.polarity()
        if got is not want:
            out.append(Violation(self.name,
                                 f"end-to-end polarity is {got.name}, "
                                 f"wanted {want.name} — add or remove one inverter"))
        return out

    def report(self, want: Polarity = Polarity.NORMAL) -> str:
        lines = [f"chain {self.name}: {len(self.segments)} segment(s), "
                 f"polarity {self.polarity().name}"]
        for s in self.segments:
            lines.append("  " + s.describe())
        viol = self.validate(want)
        if viol:
            lines.append(f"  {len(viol)} violation(s):")
            lines.extend("    " + str(x) for x in viol)
        else:
            lines.append("  OK: every boundary holds")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Segment descriptors for the pieces the router already emits.
# Each one states its ports HONESTLY, including measured decay, so the protocol
# can catch a bad composition before anything is built.
# ---------------------------------------------------------------------------

def seg_up_tower(base_cell: Pos, top_y: int, torches: int) -> Segment:
    """1x1 standing-torch climb. Regenerates, so the output is full strength; each
    torch inverts, so the polarity follows the parity of the torch count.

    Its input is a solid BLOCK (block0), driven from the side by a repeater — not
    dust. Declaring it as dust is what made the protocol pass chains that MCHPRS
    then measured as dead; the honesty audit caught it on all eleven of them."""
    x, y, z = base_cell
    pol = Polarity.NORMAL if torches % 2 == 0 else Polarity.INVERTED
    return Segment("up_tower",
                   Port(base_cell, y, Kind.BLOCK, 15),
                   Port((x, top_y, z), top_y, Kind.DUST, 15, pol),
                   needs_level=1)


def seg_source_drive(pin_cell: Pos, rep_cell: Pos, block_cell: Pos) -> Segment:
    """The source end: a gate output dust, a repeater reading it, and the repeater
    driving the up tower's base block. Modelling this explicitly is what lets the
    block-needs-a-strong-driver rule apply — without it the chain started at the
    tower and the missing driver went unnoticed."""
    # `out` names the cell that CARRIES this segment's signal — the repeater
    # itself — not the block it energises. Pointing it at the block made the
    # honesty audit (correctly) complain that the cell holds stone.
    return Segment("source_drive",
                   Port(pin_cell, pin_cell[1], Kind.DUST, 15),
                   Port(rep_cell, rep_cell[1], Kind.REPEATER_OUT, 15,
                        facing="west"),
                   needs_level=1)


def seg_trunk(start: Pos, end: Pos, plane: int, refresh_every: int = 12) -> Segment:
    """Straight corridor with refresh repeaters: the last repeater re-drives to 15,
    so the guaranteed output level depends only on the distance past it."""
    dist = sum(abs(a - b) for a, b in zip(start, end))
    tail = dist % refresh_every
    level = max(0, 15 - tail)
    return Segment("trunk",
                   Port(start, plane, Kind.DUST, 15),
                   Port(end, plane, Kind.DUST, level),
                   needs_level=1)


def seg_leg(start: Pos, end: Pos, plane: int, refresh_every: int = 12) -> Segment:
    dist = sum(abs(a - b) for a, b in zip(start, end))
    tail = dist % refresh_every
    return Segment("leg",
                   Port(start, plane, Kind.DUST, 15),
                   Port(end, plane, Kind.DUST, max(0, 15 - tail)),
                   needs_level=1)


def seg_stairs_box(in_cell: Pos, out_cell: Pos, drop: int) -> Segment:
    """Shielded staircase delivery: non-inverting, but loses one level per level
    dropped — which is exactly the fact the protocol needs in order to reject a
    deep drop instead of letting it fail silently in a world."""
    # A staircase consumes one level per level dropped, so it does not merely need
    # "some" signal — it needs more than its own depth, or it delivers zero. Stating
    # that here is what lets the protocol reject a shallow feed into a deep box,
    # which is precisely how the trunk+stairs chain failed (trunk delivered 8, the
    # 5-deep box plus its boundary bridge ate all of it).
    return Segment("stairs_box",
                   Port(in_cell, in_cell[1], Kind.DUST, 15),
                   Port(out_cell, out_cell[1], Kind.DUST, max(0, 15 - drop)),
                   needs_level=drop + 2)


def seg_tower_box(in_cell: Pos, out_cell: Pos, drop: int,
                  inverter_inside: bool = True) -> Segment:
    """Shielded tower delivery. Each rung re-drives, so depth costs no strength —
    the property the staircase lacks — but the tower inverts, so the module carries
    a compensating inverter. Declaring `inverter_inside` honestly lets the protocol
    catch the case where that inverter is missing or not wired, which is exactly the
    state TowerBox is in right now."""
    pol = Polarity.NORMAL if inverter_inside else Polarity.INVERTED
    return Segment("tower_box",
                   Port(in_cell, in_cell[1], Kind.DUST, 15),
                   Port(out_cell, out_cell[1], Kind.DUST, 15, pol),
                   needs_level=1)


def seg_feed_run(start: Pos, end: Pos) -> Segment:
    dist = sum(abs(a - b) for a, b in zip(start, end))
    return Segment("feed_run",
                   Port(start, start[1], Kind.DUST, 15),
                   Port(end, end[1], Kind.DUST, max(0, 15 - dist)),
                   needs_level=1)


def seg_pin(feed_cell: Pos, pin_cell: Pos) -> Segment:
    """A gate input pin is a west-facing repeater: it reads ONLY its west
    neighbour, and it needs at least level 1 there."""
    return Segment("gate_pin",
                   Port(feed_cell, feed_cell[1], Kind.DUST, 1),
                   Port(pin_cell, pin_cell[1], Kind.REPEATER_OUT, 15,
                        facing="west"),
                   needs_level=1)
