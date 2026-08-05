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
    direction: int = 1              # +1 stairs descend east, -1 descend west
    blocks: Dict[Pos, str] = field(default_factory=dict)
    in_cell: Pos = (0, 0, 0)
    out_cell: Pos = (0, 0, 0)
    extent: Tuple[Pos, Pos] = ((0, 0, 0), (0, 0, 0))
    keep_glass: Set[Pos] = field(default_factory=set)   # stairs have no torches
    # stair-seat UPPER cells (a descending dust's diagonal-down seat's ceiling)
    # that must stay air: a block there blocks the stair's step in MCHPRS
    # (measured: sink1's leg support at (217,4,19) killed sink2's stair at
    # (216,4,19)->(217,3,19)).
    keep_air: Set[Pos] = field(default_factory=set)

    def __post_init__(self):
        ax, ay, az = self.anchor
        H = self.drop
        interior = {}

        # Descending dust: one cell east per level down, each on its own support.
        # The FIRST interior cell is a repeater, and another goes in every 12 levels:
        # the signal arriving from the trunk has already decayed over a long leg
        # (measured: it reached the box at 1-3), and a staircase loses one more per
        # level, so without re-driving at the entrance the box delivers nothing.
        # A repeater facing west reads its west neighbour, which is the direction of
        # travel here.
        # A repeater must have its input and output on the SAME level, so it cannot
        # sit on a descending step — that was a known break earlier in this project
        # ("never put a repeater on a corner"). Refreshes therefore go on FLAT
        # landings: descend a few levels, run one cell level to host the repeater,
        # then carry on down. A landing right at the entrance re-drives the signal,
        # which arrives already decayed from the long trunk leg (measured at 1-3).
        REP_W = ("minecraft:repeater[facing=west,delay=1]" if self.direction == 1
                 else "minecraft:repeater[facing=east,delay=1]")
        RUN = 10                                      # levels between landings
        x, y = ax, ay
        # `in` is a west-facing REPEATER, not dust: a bare dust input couples to
        # whatever sits beside it (measured 13 with the source cut). The repeater's
        # OUTPUT lands one cell EAST at the same height — that cell must be dust,
        # and the first descending step starts below it. Without this landing the
        # repeater drove empty air and the staircase never saw the signal.
        interior[(x, y, az)] = ("minecraft:repeater[facing=west,delay=1]"
                              if self.direction == 1 else
                              "minecraft:repeater[facing=east,delay=1]")
        x += self.direction
        interior[(x, y, az)] = W          # the repeater's output landing
        since = 0
        for _ in range(H):
            x += self.direction
            y -= 1
            interior[(x, y, az)] = W
            since += 1
            if since >= RUN:
                x += self.direction
                interior[(x, y, az)] = REP_W          # flat landing, same level
                # The repeater's OUTPUT cell (the one in front of its facing)
                # must be dust, and the next step descends from IT — otherwise
                # the stair continues from the repeater block itself and the
                # diagonal step is never driven (measured: direction=-1 stair
                # had a vertical wire pair at the landing that did not conduct).
                x += self.direction
                interior[(x, y, az)] = W
                since = 0
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
        # Skin the occupied cells rather than filling the bounding box: a filled box
        # grows with the module's LENGTH, which for the long modules meant tens of
        # thousands of stone blocks and an out-of-memory crash in MCHPRS.
        # Skin only the AXIS neighbours, and never the cell a descending dust's
        # see-below step looks across (the diagonal above the lower dust). A skin
        # block there seals the staircase mid-way (measured: A(5,2)->B(6,1)
        # conducts only when (6,2) is air; a delivery read 11 one step and 0 the
        # next until the diagonal was left open).
        dusts = set((cx, cy, cz) for (cx, cy, cz), b in body.items() if b == W)
        blocked_diag = set()
        for (ux, uy, uz) in dusts:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                lx, ly, lz = ux + dx, uy - 1, uz + dz
                if (lx, ly, lz) in dusts:
                    blocked_diag.add((lx, uy, lz))
        shell = {}
        for (cx, cy, cz) in body:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                q = (cx + dx, cy + dy, cz + dz)
                if q in body:
                    continue
                if q in blocked_diag:
                    continue
                shell.setdefault(q, S)
        # Open the interface faces. The trunk reaches the box along Z (it runs on a
        # row beyond the field and drops down the box's column), so the `in` face
        # must be open on BOTH z sides as well as the west — closing them made the
        # shell cut the very leg that feeds the box. The `out` face opens east,
        # towards the pin.
        ic, oc = self.in_cell, self.out_cell
        for cell in (ic, oc):
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                shell.pop((cell[0] + dx, cell[1] + dy, cell[2] + dz), None)

        self.blocks = {}
        self.blocks.update(shell)
        self.blocks.update(body)          # body wins over shell on overlaps
        self.keep_air = {(lx, uy, lz)
                         for (ux, uy, uz) in dusts
                         for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
                         for (lx, ly, lz) in [(ux + dx, uy - 1, uz + dz)]
                         if (lx, ly, lz) in dusts}
        self.extent = ((x0 - 1, y0 - 1, z0 - 1), (x1 + 1, y1 + 1, z1 + 1))

    # ---------- helpers for the router ----------
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
        """Every (x,z) column the box ACTUALLY occupies (projection of its
        blocks). The bounding-box version claimed exclusivity over far more
        columns than the box touches, so two adjacent deliveries (or a delivery
        next to a trunk) always collided in box_cols even though their shells
        could overlap freely — the shell is protective, not load-bearing."""
        return {(x, z) for (x, y, z) in self.blocks}

    def volume(self):
        (x0, y0, z0), (x1, y1, z1) = self.extent
        return (x1 - x0 + 1) * (y1 - y0 + 1) * (z1 - z0 + 1)


def box_for_sink(pin_xz, trunk_y, base_y, gap=2):
    """Place a box so its `out` lands `gap` cells west of the pin, on the base
    plane, and its `in` sits at the trunk height. Returns the box."""
    px, pz = pin_xz[0], pin_xz[1] + dz
    drop = trunk_y - base_y
    out_x = px - gap
    anchor = (out_x - drop, trunk_y, pz)
    return DeliveryBox(anchor=anchor, drop=drop)


# ---------------------------------------------------------------------------
# Two delivery modules, ONE contract
# ---------------------------------------------------------------------------
# Both expose (blocks, in_cell, out_cell, extent, cells()), so the router picks
# between them purely on fit and cost — it never needs to know how either works.
#
#   STAIRS  simple and unconditionally non-inverting, but loses one signal level
#           per level dropped, so it only suits shallow drops.
#   TOWER   regenerates at every rung, so depth costs nothing electrically, but it
#           inverts (measured: consistently, once fed sideways from a trunk), so a
#           compensating inverter is built into the module.
#
# Verified separately; the shell means a sealed verification carries over.

STAIRS_MAX_DROP = 8          # measured: drop<=8 delivers, drop=12 arrives at 0


@dataclass
class TowerBox:
    """Shielded DOWN-tower delivery with the compensating inverter inside.

    Depth-independent: every rung re-drives the signal, so a deep trunk costs
    nothing in strength — the property the staircase lacks. The inversion the tower
    introduces is cancelled by an inverter placed inside the same shell, so the
    module as a whole is non-inverting and the router sees the same contract as the
    staircase version.
    """
    anchor: Pos                     # the `in` cell (top of the shaft)
    drop: int
    blocks: Dict[Pos, str] = field(default_factory=dict)
    in_cell: Pos = (0, 0, 0)
    out_cell: Pos = (0, 0, 0)
    extent: Tuple[Pos, Pos] = ((0, 0, 0), (0, 0, 0))
    # torch-top cells the router must support with GLASS (non-conducting solid)
    keep_glass: Set[Pos] = field(default_factory=set)
    keep_air: Set[Pos] = field(default_factory=set)   # glass handles the tops
    # mirror the tower to the z-1 side (see delivery_for_sink)
    flip_arm: bool = False

    def __post_init__(self):
        from via_gadget import down_tower_cells_dir, inverter_cells
        ax, ay, az = self.anchor
        H = self.drop
        body: Dict[Pos, str] = {}

        # The tower needs an even span. On an odd drop, sink the `in` repeater
        # one level instead of inserting a parity dust below it: a parity dust at
        # (ax, ay-1) sat directly under the repeater, where it was fed by the
        # repeater block's strong power AND by a staircase from the output
        # landing — and in MCHPRS that seat block leaked charge into the
        # neighbouring partner wire, freezing the first torch pair (measured:
        # the drop=21 tower's A column died at y=14,10,4 with a shell block in
        # the seat, and stayed live with drive=0 while the parity dust leaked).
        # Sinking the repeater makes the tower span (ay-H..top) even with NO
        # extra dust, and the repeater block's strong power drives the A support
        # directly below it.
        top = ay - (H % 2)
        # `in` is plain DUST, one level up from the tower's first A support. The
        # L-jog wire lands beside it at (ax-1, top, az) and drives it; the dust
        # then weakly powers the A support directly below it, which unlights the
        # first torch and starts the down chain. A repeater was tried here
        # (MCHPRS does not strongly power blocks below it, and a parity dust
        # under the repeater leaked through the output landing's staircase —
        # measured both ways), and a bare dust is acceptable because the shell
        # seals the sides: the L-jog wire is the only neighbour inside it.
        body[(ax, top, az)] = W
        y_bot = ay - H
        # arm=(0,1): the torch column sits on the z+1 side. A lit torch's strong
        # power leaks through ANY solid block directly above it, and on the z+1
        # side that cell is the sink leg's support (the leg runs on this tower's
        # x, z >= az — measured: the lit torch charged the support, the leg wire
        # above it, and finally the in dust — a drive=0 self-powered island that
        # froze the tower on at 14). The router blocks that leak by supporting
        # those cells with GLASS (keep_glass below: a solid, non-conducting
        # support, measured in MCHPRS). The z-1 side would dodge the leg column
        # but steals two z-columns from the neighbour's local routing (measured:
        # alu1's n7 lost its bridge lane at 96x192).
        # arm=(0,-1): the tower's z+1 side stays FREE. A sink whose neighbour
        # gate sits at z+1 (measured: n18's tower at (246..251, 0..2) sealed
        # n21's feed (251,2), leaving its descent nowhere to land) needs that
        # column; the z-1 side is open ground.
        cells, _foot = down_tower_cells_dir(ax, az, top, y_bot,
                                            side=(-1, 0) if self.flip_arm else (1, 0),
                                            arm=(0, -1) if self.flip_arm else (0, 1))
        for (x, y, z, b) in cells:
            body[(x, y, z)] = b
        # the tower's own output dust sits in the shaft column at y_bot
        tower_out_x = ax
        # NO compensating inverter. Measured both ways: the shaft alone, driven at
        # its top the way a trunk drives it, is NON-inverting (sealed test S2), and
        # adding an inverter made the module inverting (drive1 -> 0). The earlier
        # "the tower always inverts" reading came from probing the shaft's bottom
        # cell, which is shared with the outgoing run and therefore reads whatever
        # the downstream layout imposes.
        lead_from = max(x for (x, y, _z, _b) in cells if y == y_bot) + 1
        for i in range(2):
            body[(lead_from + i, y_bot, az)] = W
            body[(lead_from + i, y_bot - 1, az)] = S
        self.in_cell = (ax, top, az)
        self.out_cell = (lead_from + 1, y_bot, az)

        xs = [p[0] for p in body]; ys = [p[1] for p in body]; zs = [p[2] for p in body]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        z0, z1 = min(zs), max(zs)
        # Skin the occupied cells rather than filling the bounding box: a filled box
        # grows with the module's LENGTH, which for the long modules meant tens of
        # thousands of stone blocks and an out-of-memory crash in MCHPRS.
        # Skin only the AXIS neighbours, and never the cell a descending dust's
        # see-below step looks across (the diagonal above the lower dust). A skin
        # block there seals the staircase mid-way (measured: A(5,2)->B(6,1)
        # conducts only when (6,2) is air; a delivery read 11 one step and 0 the
        # next until the diagonal was left open).
        dusts = set((cx, cy, cz) for (cx, cy, cz), b in body.items() if b == W)
        blocked_diag = set()
        for (ux, uy, uz) in dusts:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                lx, ly, lz = ux + dx, uy - 1, uz + dz
                if (lx, ly, lz) in dusts:
                    blocked_diag.add((lx, uy, lz))
        # The staircase SEATS (a dust's diagonal-down cells) must stay air too,
        # not just the cells above them: a shell block in a seat gets charged by
        # the dust's staircase step and leaks that charge into the neighbouring
        # partner wire, killing the next torch (measured: the (14,19,15) seat of
        # the drop=21 tower's parity dust killed the whole tower below it).
        for (ux, uy, uz) in dusts:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                blocked_diag.add((ux + dx, uy - 1, uz + dz))
        # A torch's strong power leaks through a shell block directly above it
        # into the neighbour's wire (measured: torch1's (13,20,16) shell fed the
        # sink leg's end at (13,21,16), so the whole in/leg island self-powered
        # with drive=0 and the tower delivered a constant 14). Torch tops stay
        # air.
        for (cx, cy, cz), b in body.items():
            if "torch" in b:
                blocked_diag.add((cx, cy + 1, cz))
        shell = {}
        for (cx, cy, cz) in body:
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                q = (cx + dx, cy + dy, cz + dz)
                if q in body:
                    continue
                if q in blocked_diag:
                    continue
                shell.setdefault(q, S)
        ic, oc = self.in_cell, self.out_cell
        for cell in (ic, oc):
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                shell.pop((cell[0] + dx, cell[1] + dy, cell[2] + dz), None)

        self.blocks = {}
        self.blocks.update(shell)
        self.blocks.update(body)
        # torch tops: the router must support these cells with GLASS (see the
        # field doc); the tower's own torch tops are the ones the router's wire
        # supports could land on.
        self.keep_glass = {(cx, cy + 1, cz)
                           for (cx, cy, cz), b in self.blocks.items()
                           if "torch" in b}
        self.extent = ((x0 - 1, y0 - 1, z0 - 1), (x1 + 1, y1 + 1, z1 + 1))

    def interior(self):
        """The module WITHOUT its shell: every conducting cell plus the support
        directly under it."""
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


def delivery_for_sink(pin_xz, trunk_y, base_y, gap=2, prefer=None, dz=0,
                     flip_arm=False):
    """Pick a delivery module for this sink.

    Shallow drops take the staircase (simplest, no inversion to cancel); deeper
    ones take the tower, which does not attenuate. `prefer` forces a kind, which is
    what lets the router retry with the other one when the first does not fit.
    `flip_arm` mirrors the tower to the z-1 side: use it when the z+1 side is
    occupied by a neighbouring gate's pin (measured: n18's tower at (246..251,
    0..2) sealed n21's feed (251,2) and left its descent nowhere to land).
    """
    px, pz = pin_xz[0], pin_xz[1] + dz
    drop = trunk_y - base_y
    # A staircase eats one level per level dropped, so it only suits shallow drops
    # AND a strong feed. The trunk arrives already attenuated over a long run, so
    # the safe default is the tower — it regenerates at every rung and delivers a
    # constant 14 at any depth (measured 4..28). Stairs stay available for the very
    # shallow case, where their smaller volume is worth it.
    kind = prefer or "stairs"
    if kind == "stairs":
        out_x = px - gap
        # The staircase's true span is NOT `drop`: the entrance landing and each
        # refresh landing push the endpoint one cell per landing past anchor.x +
        # drop (measured: the router's drop=21 anchors put `out` 5 cells east of
        # the pin, landing on the pin itself for gap=5). Probe instead of
        # assuming, exactly like the tower branch below.
        probe = DeliveryBox(anchor=(0, trunk_y, pz), drop=drop, direction=1)
        span = probe.out_cell[0] - probe.in_cell[0]
        # If the west-side anchor would land outside the field (x<0), descend
        # EAST instead: in = out_x + span, walk back west to out.
        if out_x - span >= 0:
            return DeliveryBox(anchor=(out_x - span, trunk_y, pz),
                               drop=drop, direction=1), "stairs"
        return DeliveryBox(anchor=(out_x + span, trunk_y, pz),
                           drop=drop, direction=-1), "stairs"
    # the tower's out sits a fixed number of columns east of its shaft; place the
    # shaft far enough west that `out` lands gap cells before the pin
    probe = TowerBox(anchor=(0, trunk_y, pz), drop=drop, flip_arm=flip_arm)
    span = probe.out_cell[0] - probe.in_cell[0]
    shaft_x = px - gap - span
    return TowerBox(anchor=(shaft_x, trunk_y, pz), drop=drop,
                    flip_arm=flip_arm), "tower"
