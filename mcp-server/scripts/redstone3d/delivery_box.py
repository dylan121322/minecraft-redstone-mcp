"""
delivery_box.py — the sink delivery as a SELF-CONTAINED, SHIELDED module.

Why this exists: the previous delivery was eight bare cells whose behaviour
depended on seven separate things at once — tower rotation, torch parity, the
parity bridge, the compensating inverter, the z-distance to neighbouring towers,
the pin's west-only input, and sharing the y0 plane with local routing. Fixing any
one of them broke an assumption behind another, so a dozen rounds of edits never
converged, and "passes in a sealed test" never implied "passes inside a module".

The fix is architectural, not geometric:

  * the delivery occupies a FIXED cuboid;
  * that cuboid carries its own STONE SHELL, so neighbouring towers, local wiring
    and the floor slab cannot reach inside — interference becomes physically
    impossible instead of merely discouraged;
  * it exposes exactly TWO interface cells: `in` on the top face (fed by the trunk)
    and `out` on the bottom face (drives the pin's feed cell);
  * polarity is settled INSIDE and verified once; the router never learns how many
    torches there are or which way they face.

Because the shell is part of the module, a sealed test of the box IS a test of the
box in situ. The router's only job becomes packing: find somewhere the cuboid fits.

Interface contract
------------------
    box = DeliveryBox(anchor=(x, y, z), drop=H)
    box.blocks   -> {(x,y,z): blockstate}   everything, shell included
    box.in_cell  -> the cell the trunk must drive
    box.out_cell -> the cell that drives the pin's feed
    box.extent   -> ((x0,y0,z0), (x1,y1,z1)) inclusive bounds to reserve
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Tuple

Pos = Tuple[int, int, int]

W = "minecraft:redstone_wire"
S = "minecraft:stone"
TORCH_STAND = "minecraft:redstone_torch"


def _wt(facing: str) -> str:
    return f"minecraft:redstone_wall_torch[facing={facing}]"


@dataclass
class DeliveryBox:
    """A shielded staircase drop from `in` (top) to `out` (bottom).

    Geometry choice: a plain see-below STAIRCASE, not a torch tower. A staircase
    is unconditionally non-inverting and needs no parity reasoning at all — the
    torch-based towers were the source of every polarity contradiction. Its cost is
    horizontal length (one cell per level), which is affordable here because the
    box is placed on the trunk side where there is open ground, and because the
    shell makes its footprint predictable.

    Layout for drop=H (interior runs west→east while descending):
        interior x: anchor.x .. anchor.x + H
        interior y: anchor.y - H .. anchor.y
        interior z: anchor.z
        shell: one stone layer around the whole interior
    """
    anchor: Pos                     # the `in` cell (top of the descent)
    drop: int                       # how many levels to descend (>= 1)
    blocks: Dict[Pos, str] = field(default_factory=dict)
    in_cell: Pos = (0, 0, 0)
    out_cell: Pos = (0, 0, 0)
    extent: Tuple[Pos, Pos] = ((0, 0, 0), (0, 0, 0))

    def __post_init__(self):
        ax, ay, az = self.anchor
        H = self.drop
        interior = {}

        # descending dust: one cell east per level down, each on its own support
        x, y = ax, ay
        interior[(x, y, az)] = W                      # the `in` cell
        for _ in range(H):
            x += 1
            y -= 1
            interior[(x, y, az)] = W
        self.in_cell = (ax, ay, az)
        self.out_cell = (x, y, az)

        # supports directly under every dust cell
        supports = {(cx, cy - 1, cz): S for (cx, cy, cz) in interior}

        body = {}
        body.update(supports)
        body.update(interior)

        # bounds of the interior (dust + its supports)
        xs = [p[0] for p in body]; ys = [p[1] for p in body]; zs = [p[2] for p in body]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        z0, z1 = min(zs), max(zs)

        # SHELL: a stone skin one cell thick around the interior, except at the two
        # interface cells, which must stay reachable from outside.
        shell = {}
        for sx in range(x0 - 1, x1 + 2):
            for sy in range(y0 - 1, y1 + 2):
                for sz in range(z0 - 1, z1 + 2):
                    inside = (x0 <= sx <= x1 and y0 <= sy <= y1 and z0 <= sz <= z1)
                    if inside:
                        continue
                    shell[(sx, sy, sz)] = S
        # open the two interface faces so the trunk and the feed run can connect
        shell.pop((self.in_cell[0] - 1, self.in_cell[1], self.in_cell[2]), None)
        shell.pop((self.out_cell[0] + 1, self.out_cell[1], self.out_cell[2]), None)

        self.blocks = {}
        self.blocks.update(shell)
        self.blocks.update(body)          # body wins over shell on overlaps
        self.extent = ((x0 - 1, y0 - 1, z0 - 1), (x1 + 1, y1 + 1, z1 + 1))

    # ---------- helpers for the router ----------
    def cells(self):
        """Every (x,z) column the box occupies — what the router must keep clear."""
        (x0, _y0, z0), (x1, _y1, z1) = self.extent
        return {(x, z) for x in range(x0, x1 + 1) for z in range(z0, z1 + 1)}

    def volume(self):
        (x0, y0, z0), (x1, y1, z1) = self.extent
        return (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)


def box_for_sink(pin_xz, trunk_y, base_y, gap=2):
    """Place a box so its `out` lands `gap` cells west of the pin, on the base
    plane, and its `in` sits at the trunk height. Returns the box."""
    px, pz = pin_xz
    drop = trunk_y - base_y
    out_x = px - gap
    anchor = (out_x - drop, trunk_y, pz)
    return DeliveryBox(anchor=anchor, drop=drop)
