"""
trunk_box.py — the upstream half of a global net as ONE shielded module.

Why: the delivery boxes reach 100% in sealed AND hostile conditions, while the
global chain as a whole sits at 3/10. The difference is not the physics — it is that
the upstream half is five hand-joined pieces (source repeater, up tower, trunk row,
column leg, hand-offs between them) with ten-odd boundaries, each of which I had to
reason about by hand. Every debugging round removed one fault class and revealed the
next, because nothing enforced the boundaries.

The delivery box solved exactly this by shrinking its interface to two cells and
carrying its own shell. TrunkBox applies the same treatment upstream:

    in_cell   the gate output dust of the source (read, not driven, by the box)
    out_cell  a dust at the far end, at the trunk plane, ready for a DeliveryBox
    shell     stone skin, so local routing / other nets / the floor cannot reach in

Inside, the module owns the whole route: drive repeater, climb, the long horizontal
run with refreshes, and the turn toward the sink's row. Because the shell makes a
sealed test equivalent to the in-situ case, verifying it once settles it.

Geometry, all inside the shell:

      y = plane          ┌───── run east ─────┐ turn ─┐
                         │                     │      │
      y = base+1..plane   climb (torch ladder)         │ leg south/north
      y = base            in_cell ── repeater ─┘       └── out_cell (at plane)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Tuple, List

Pos = Tuple[int, int, int]

W = "minecraft:redstone_wire"
S = "minecraft:stone"
TORCH = "minecraft:redstone_torch"
REFRESH = 12


def _rep(facing: str) -> str:
    return f"minecraft:repeater[facing={facing},delay=1]"


@dataclass
class TrunkBox:
    """Source pin -> climb -> horizontal run -> leg -> out, in one shielded box.

    `plane` must be base_y + 4k + 1 so the torch ladder climbs an even number of
    torches and the transfer is non-inverting.
    """
    src_cell: Pos            # the gate output dust the box reads
    plane: int               # trunk Y inside the box
    run_to_x: int            # how far east the horizontal run goes
    leg_to_z: int            # which z the leg ends on (the sink's row)
    climb_x: int = -1        # optional explicit climb column (router-assigned to
                             # dodge other nets' ladders/legs); -1 = auto by sz
    leg_x: int = -1          # optional explicit LEG column: the vertical leg
                             # walks HERE instead of in the climb column, so it
                             # can dodge the gate rows the climb column crosses.
                             # -1 = leg stays in the climb column
    blocks: Dict[Pos, str] = field(default_factory=dict)
    in_cell: Pos = (0, 0, 0)
    out_cell: Pos = (0, 0, 0)
    extent: Tuple[Pos, Pos] = ((0, 0, 0), (0, 0, 0))
    torches: int = 0

    def __post_init__(self):
        sx, sy, sz = self.src_cell
        base = sy
        body: Dict[Pos, str] = {}

        # --- source drive: repeater east of the pin, reading it
        body[(sx, base, sz)] = W                  # the pin's own dust (in_cell)
        body[(sx + 1, base, sz)] = _rep("west")   # reads the pin, drives the climb

        # Climb column: router-assigned when given (the router knows which
        # columns the earlier nets' ladders and legs already own); otherwise a
        # fixed offset by source-z parity. Fixed offsets were never enough: all
        # source pins sit on x=0 at z = 19 + 12k, and 12 divides any offset
        # pattern, so adjacent nets always landed on the same column (measured:
        # n2's torch at (3,5,31) collided with n4's cross-leg repeater there).
        cx = self.climb_x if self.climb_x >= 0 else (sx + (3 if sz % 2 else 2))
        span = self.plane - 1 - base
        assert span % 2 == 0, "climb needs an even span"
        self.torches = span // 2
        y = base
        for _ in range(self.torches):
            body[(cx, y, sz)] = S
            body[(cx, y + 1, sz)] = TORCH
            y += 2
        body[(cx, y, sz)] = S                     # top block
        body[(cx, y + 1, sz)] = W                 # readable dust at `plane`

        # --- LEG FIRST: turn onto this net's corridor row, THEN run east.
        # The old order ran east along z = sz (the SOURCE's row) and only turned
        # afterwards. But the source's row is a GATE row: measured on alu1's n32,
        # a run from x=104 to x=282 along z=1 crossed sixteen gate columns
        # (x=18..316 are gate bodies on that row), so the box was rejected for
        # collision every time. Turning onto the corridor row first keeps the long
        # horizontal stretch inside the reserved corridor, which is gate-free by
        # construction, and leaves only the 3-cell climb on the source's row.
        # Vertical leg column: the climb column crosses the source's own gate
        # row AND every other gate row between it and the corridor (measured on
        # Control: n16's leg along x=24 hit gate bodies at z=53-55, 72-74, 91-93).
        # When the router assigns leg_x, walk horizontally to it FIRST (on the
        # source's row), then vertically in a gate-free column.
        leg_x = self.leg_x if self.leg_x >= 0 else cx
        step = 1 if self.leg_to_z >= sz else -1
        facing = "north" if step == 1 else "south"   # measured: travel +z -> north
        run = 0
        # horizontal jog from the climb column to leg_x (on the source's row)
        while cx < leg_x:
            cx += 1
            body[(cx, self.plane - 1, sz)] = S
            run += 1
            if run >= REFRESH:
                body[(cx, self.plane, sz)] = _rep("west")
                run = 0
            else:
                body[(cx, self.plane, sz)] = W
        # vertical leg in the (gate-free) leg column
        z = sz
        while z != self.leg_to_z:
            z += step
            body[(leg_x, self.plane - 1, z)] = S
            run += 1
            if run >= REFRESH and z != self.leg_to_z:
                body[(leg_x, self.plane, z)] = _rep(facing)
                run = 0
            else:
                body[(leg_x, self.plane, z)] = W
        leg_z = self.leg_to_z

        # --- horizontal run east along the corridor row, refreshed.
        # `run` carries the leg's leftover distance: a repeater cannot sit ON the
        # corner (its input and output axes differ), so the unrefreshed cells from
        # the leg must count toward the run's first refresh or the signal dies in
        # the corner (measured: 10 + 12 = 22 unrefreshed).
        x = leg_x
        while x < self.run_to_x:
            x += 1
            body[(x, self.plane - 1, leg_z)] = S
            run += 1
            if run >= REFRESH and x != self.run_to_x:
                body[(x, self.plane, leg_z)] = _rep("west")   # travel +x reads west
                run = 0
            else:
                body[(x, self.plane, leg_z)] = W
        turn_x = x

        self.in_cell = (sx, base, sz)
        self.out_cell = (turn_x, self.plane, self.leg_to_z)

        # --- shell around everything, openings at the two interface cells
        xs = [p[0] for p in body]; ys = [p[1] for p in body]; zs = [p[2] for p in body]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        z0, z1 = min(zs), max(zs)
        # Shell = a skin hugging the OCCUPIED cells, not a filled bounding box.
        # Filling the box was catastrophic here: this module is long and thin (the
        # run reaches hundreds of cells), so the bounding volume ran to 86k-265k
        # blocks and MCHPRS tried to allocate 3.5 GB and died — which is why runs
        # appeared to "finish with no output". Skinning only the real neighbours
        # keeps the block count proportional to the wiring.
        shell: Dict[Pos, str] = {}
        # Skin the axis neighbours EXCEPT the cell that a descending dust's
        # see-below step looks into. Measured: A(5,2)->B(6,1) conducts only when
        # the diagonal cell (6,2) is AIR; a skin that fills it seals the staircase
        # mid-way (the box delivered 11 at one step, 0 at the next). Any cell that
        # sits above-east (or above-west, above-south, above-north) of a LOWER dust
        # must be left open, because it is exactly what a higher dust sees across.
        # For every pair (upper dust at u, lower dust at l = u + (dx,-1,dz)),
        # the see-below step needs the cell directly ABOVE l — i.e. (u.x+dx, u.y, u.z)
        # — to stay AIR. It is exactly where the diagonal look crosses, and a skin
        # block there seals the staircase (measured: A(5,2)->B(6,1) conducts only
        # with (6,2) empty).
        dusts = set((cx, cy, cz) for (cx, cy, cz), b in body.items() if b == W)
        blocked_diag = set()
        for (ux, uy, uz) in dusts:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                lx, ly, lz = ux + dx, uy - 1, uz + dz
                if (lx, ly, lz) in dusts:
                    blocked_diag.add((lx, uy, lz))   # above the lower dust
        for (cx, cy, cz) in body:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                q = (cx + dx, cy + dy, cz + dz)
                if q in body:
                    continue
                if q in blocked_diag:
                    continue
                shell.setdefault(q, S)
        # Clear every neighbour of the two interface cells. With a skin-tight shell
        # the interface is wrapped on all sides, so listing a couple of openings (as
        # the filled-box version could afford to) sealed the very boundary the next
        # module connects to — the cascade went from passing to dead.
        ic, oc = self.in_cell, self.out_cell
        for cell in (ic, oc):
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                shell.pop((cell[0] + dx, cell[1] + dy, cell[2] + dz), None)

        self.blocks = {}
        self.blocks.update(shell)
        self.blocks.update(body)
        self.extent = ((x0 - 1, y0 - 1, z0 - 1), (x1 + 1, y1 + 1, z1 + 1))

    def interior(self):
        """The module WITHOUT its shell: every conducting cell plus the support
        directly under it. The skin leaks charge between modules (stone conducts
        when energised), so the non-box design removes it and isolates by air
        gaps + reserved columns instead."""
        out = {}
        for p, b in self.blocks.items():
            if b != S:
                out[p] = b
                below = (p[0], p[1] - 1, p[2])
                if below in self.blocks and self.blocks[below] == S:
                    out[below] = S
        return out

    def cells(self):
        """The (x, z) columns this box ACTUALLY occupies — the projection of its
        blocks (interior + shell). NOT the bounding box: the old version returned
        every column in the extent rectangle, which for a long trunk is ~17x the
        real footprint (measured: 12489 vs 732 for a 200-cell run). box_cols used
        that to claim exclusivity, so ANY two long trunks collided and every net
        after the first failed (measured: 423-4800 conflicts per net). Only the
        columns that carry a block can conflict with another box."""
        return {(x, z) for (x, y, z) in self.blocks}

    def volume(self):
        (x0, y0, z0), (x1, y1, z1) = self.extent
        return (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
