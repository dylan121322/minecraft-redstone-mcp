"""
connector.py — the module that joins two shielded modules.

Where this comes from: packaging the upstream (TrunkBox) and the delivery
(DeliveryBox / TowerBox) each into a shielded module took the global path from ten
hand-checked boundaries down to one. Every module passes sealed AND with hostile
geometry pressed against its shell — but the remaining boundary was still wired by
the caller, and the cascade failed there. A skin-tight shell wraps its interface on
all sides, so "just lay some dust between them" is not a definition of a joint.

So the joint becomes a module too, with the same discipline:

    Connector(a_out, b_in)
      .blocks    everything, its own skin included
      .a_cell    the cell it expects the upstream module's `out` to be
      .b_cell    the cell it will drive, i.e. the downstream module's `in`

It carries the signal between two arbitrary cells on the same plane (an L-shaped
run: along x, then along z), refreshes every 12 cells, and opens its skin exactly at
the two endpoints so both neighbours can reach it. Because the endpoints are stated
rather than assumed, a mismatch is a checkable fact — signal_protocol can validate
this joint like any other segment.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Tuple

Pos = Tuple[int, int, int]

W = "minecraft:redstone_wire"
S = "minecraft:stone"
REFRESH = 12


def _rep(facing: str) -> str:
    return f"minecraft:repeater[facing={facing},delay=1]"


@dataclass
class Connector:
    """An L-shaped, shielded link from `a_out` to `b_in` on one plane.

    Both endpoints must share a Y. The path runs along x first, then along z; a
    repeater cannot sit on the corner (its input and output axes differ), so the
    leftover distance from the x leg is carried into the z leg's refresh counter —
    the same trap that killed TrunkBox's corner until it was fixed there.
    """
    a_out: Pos
    b_in: Pos
    # Cells belonging to the neighbouring modules. The connector must not place
    # anything there: its skin naturally wraps past an interface into the module on
    # the other side, and 3 of the 31 shared cells disagreed about their contents,
    # so whichever module was emitted last won. That is precisely why the cascade
    # behaved differently from case to case (dead, then a constant 14, then dead).
    keep_out: frozenset = frozenset()
    blocks: Dict[Pos, str] = field(default_factory=dict)
    a_cell: Pos = (0, 0, 0)
    b_cell: Pos = (0, 0, 0)
    extent: Tuple[Pos, Pos] = ((0, 0, 0), (0, 0, 0))
    length: int = 0

    def __post_init__(self):
        ax, ay, az = self.a_out
        bx, by, bz = self.b_in
        assert ay == by, "connector endpoints must share a plane"
        y = ay
        body: Dict[Pos, str] = {}

        # --- leg along x, from just after a_out toward b's column
        xstep = 1 if bx >= ax else -1
        xfacing = "west" if xstep == 1 else "east"     # travel +x reads west
        run = 0
        x = ax
        while x != bx:
            x += xstep
            body[(x, y - 1, az)] = S
            run += 1
            if run >= REFRESH and x != bx:
                body[(x, y, az)] = _rep(xfacing)
                run = 0
            else:
                body[(x, y, az)] = W

        # --- leg along z, carrying the leftover refresh distance across the corner
        zstep = 1 if bz >= az else -1
        zfacing = "north" if zstep == 1 else "south"   # travel +z reads north
        z = az
        while z != bz:
            z += zstep
            body[(bx, y - 1, z)] = S
            run += 1
            if run >= REFRESH and z != bz:
                body[(bx, y, z)] = _rep(zfacing)
                run = 0
            else:
                body[(bx, y, z)] = W

        self.a_cell = self.a_out
        self.b_cell = self.b_in
        self.length = abs(bx - ax) + abs(bz - az)

        if not body:                       # endpoints adjacent: nothing to lay
            self.blocks = {}
            self.extent = ((ax, y - 1, az), (bx, y + 1, bz))
            return

        # --- skin, then open both endpoints on every side
        shell: Dict[Pos, str] = {}
        for (cx, cy, cz) in body:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        q = (cx + dx, cy + dy, cz + dz)
                        if q in body:
                            continue
                        shell.setdefault(q, S)
        for cell in (self.a_cell, self.b_cell):
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                shell.pop((cell[0] + dx, cell[1] + dy, cell[2] + dz), None)
            shell.pop(cell, None)
        # never touch a neighbour module's cells
        for cell in self.keep_out:
            shell.pop(cell, None)
            body.pop(cell, None)

        self.blocks = {}
        self.blocks.update(shell)
        self.blocks.update(body)

        xs = [p[0] for p in self.blocks]; ys = [p[1] for p in self.blocks]
        zs = [p[2] for p in self.blocks]
        self.extent = ((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))

    def cells(self):
        (x0, _y0, z0), (x1, _y1, z1) = self.extent
        return {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}
