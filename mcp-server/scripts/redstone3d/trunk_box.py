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

        # --- climb: 1x1 torch ladder, block0 driven by that repeater
        cx = sx + 2
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

        # --- horizontal run east along z = sz, refreshed
        run = 0
        x = cx
        while x < self.run_to_x:
            x += 1
            body[(x, self.plane - 1, sz)] = S
            run += 1
            if run >= REFRESH and x != self.run_to_x:
                body[(x, self.plane, sz)] = _rep("west")   # travel +x reads west
                run = 0
            else:
                body[(x, self.plane, sz)] = W
        turn_x = x

        # --- leg along z toward the sink's row, refreshed
        # The run and the leg used to count refreshes independently, so the distance
        # left over at the end of the run plus the first stretch of the leg could add
        # up past 15 and the signal died in the corner (measured: run ended 10 cells
        # after its last repeater, the leg then went 12 more — 22 unrefreshed).
        # A repeater cannot sit ON the corner (its input and output axes differ), so
        # the leftover is carried into the leg's counter instead.
        step = 1 if self.leg_to_z >= sz else -1
        facing = "north" if step == 1 else "south"   # measured: travel +z -> north
        run = run                                    # carry the leftover distance
        z = sz
        while z != self.leg_to_z:
            z += step
            body[(turn_x, self.plane - 1, z)] = S
            run += 1
            if run >= REFRESH and z != self.leg_to_z:
                body[(turn_x, self.plane, z)] = _rep(facing)
                run = 0
            else:
                body[(turn_x, self.plane, z)] = W

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
        (x0, _y0, z0), (x1, _y1, z1) = self.extent
        return {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}

    def volume(self):
        (x0, y0, z0), (x1, y1, z1) = self.extent
        return (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)
