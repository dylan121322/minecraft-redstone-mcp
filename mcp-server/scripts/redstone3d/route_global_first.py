"""
route_global_first.py — the global-first flow from PARTITION_PLAN v2.

Order (deliberately the reverse of the old router):
  P1  build every GLOBAL net as a dedicated trunk corridor on a cross layer,
      with 1x1 UP towers at the source and 2x2 DOWN towers into each sink pin;
  P2  reserve those columns so the plane router cannot walk into them;
  P3  route LOCAL nets per zone on y0 with the existing planar router;
  P4  merge and report.

Why this order: measurement showed partitioning only rescues local nets
(ALU_Control local 19->23, shorts 7->0) while most failures are global nets
(ImmGen 27 of 41). Deciding the long connections first makes them a first-class
constraint instead of leftovers, and the corridor discipline (one net per row,
rows >=3 apart, refresh every 12 cells) makes them structurally short-free —
verified end to end at 300 cells in test_trunk_e2e.
"""
from __future__ import annotations
import sys, os, json, copy, time
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))

from via_gadget import (up_tower_cells, trunk_cells, down_tower_cells_dir,
                        inverter_cells)
from route_buildable import BuildableRouter
from reserve import ReserveMap, reservation_from_cells
from delivery_box import delivery_for_sink, STAIRS_MAX_DROP
from trunk_box import TrunkBox

Pos = Tuple[int, int, int]
XZ = Tuple[int, int]
W = "minecraft:redstone_wire"; S = "minecraft:stone"
_PLANE_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1),
                (1, 1), (1, -1), (-1, 1), (-1, -1)]

TRACK_PITCH = 3          # measured minimum isolated corridor spacing
LAYER_PITCH = 4          # Y between cross layers (keeps tower torch count even)


@dataclass
class GlobalResult:
    blocks: Dict[Pos, str] = field(default_factory=dict)
    # protected regions for the multi-cell delivery gadgets, so nothing can write
    # over a tower rung or an inverter torch without it being detected
    rmap: "ReserveMap" = field(default_factory=lambda: ReserveMap())
    reserved: Set[XZ] = field(default_factory=set)     # y0 columns consumed
    routed: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    trunk_rows: Dict[str, int] = field(default_factory=dict)
    wire_count: int = 0


class GlobalFirstRouter:
    def __init__(self, placement, zone_width: int = 64, trunk_y: int = 5,
                 zone_depth: int = 128):
        self.pl = placement
        self.W = zone_width
        self.Wz = zone_depth        # z extent of a zone (see _zone)
        mn, mx = placement.bounds
        self.x0, self.x1 = mn[0], mx[0]
        self.z0, self.z1 = mn[2], mx[2]
        self.base_y = mn[1]
        # Trunk height satisfies BOTH ends: the source UP tower delivers at
        # base+4k+1 (non-inverting only for an even torch count), and the sink
        # DeliveryBox is a staircase that loses one level per level dropped, so it
        # is only verified for drops <= 8. y=5 is the value that fits both.
        self.trunk_y = trunk_y
        self.cell_xz: Set[XZ] = {(p[0], p[2]) for p in placement.occupancy}
        # (x,z) -> net for every column a delivery tower occupies. A tower spans
        # two z rows, so two towers a few rows apart interfere: the neighbour's
        # torch energises this tower's support block and holds its last rung dark
        # (measured on n4 — 15 at y=2, 0 at y=0). A clear ring is required.
        self.tower_cols: Dict[XZ, str] = {}
        # (x,z) -> net for every column a DeliveryBox occupies; boxes are
        # shielded, so they only need to not overlap each other.
        self.box_vox: Dict[Pos, str] = {}
        # net -> its OWN trunk Y. Sharing one plane let a net's leg cross
        # another net's trunk row; separate layers remove that entirely.
        self.net_trunk_y: Dict[str, int] = {}
        self.pin_xz: Dict[XZ, str] = {}
        for n, p in placement.net_sources.items():
            self.pin_xz[(p[0], p[2])] = n
        for n, ks in placement.net_sinks.items():
            for p in ks:
                self.pin_xz[(p[0], p[2])] = n
        # exact (x,y,z) cells of gate bodies AND pins — the delivery-box column
        # check was height-blind (a shell 20 blocks above a pin rejected the
        # whole box), so the sink loop now checks exact cells + conduction
        # range instead of column projection.
        self.occ_cells: Set[Pos] = set(placement.occupancy)
        self.pins_by_net: Dict[str, List[Pos]] = {}
        for n, p in placement.net_sources.items():
            self.pins_by_net.setdefault(n, []).append(p)
        for n, ks in placement.net_sinks.items():
            self.pins_by_net.setdefault(n, []).extend(list(ks))

    # ---------- classification ----------
    # Zones are TWO-DIMENSIONAL. Splitting on x alone left every z-long connection
    # classified as "local": Forwarding's field is 121 x 820, so 62 of its 84 local
    # nets landed in a single zone and 30 of them could not be routed — all of them
    # long (spans 110-750) with their sink feed cells still free, i.e. the plane was
    # simply full. Cutting z as well spreads that load and promotes the long
    # z-runs to globals, which get a verified corridor instead.
    def _zone(self, x: int, z: int = None):
        if z is None:                     # legacy single-arg use
            return (x - self.x0) // self.W
        return ((x - self.x0) // self.W, (z - self.z0) // self.Wz)

    def _net_zones(self, n) -> Set:
        pts = [self.pl.net_sources[n]] + list(self.pl.net_sinks[n])
        return {self._zone(p[0], p[2]) for p in pts}

    def classify(self):
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        local, glob = [], []
        for n in nets:
            (local if len(self._net_zones(n)) == 1 else glob).append(n)
        return nets, local, glob

    # ---------- P1: global trunks ----------
    def build_globals(self, glob: List[str]) -> GlobalResult:
        res = GlobalResult()
        free_rows = [z for z in range(self.z1 + TRACK_PITCH,
                                      self.z1 + TRACK_PITCH * (len(glob) + 2),
                                      TRACK_PITCH)]
        # longest first: they gain most from a clean corridor
        def span(n):
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            return max(xs) - min(xs)

        for i, n in enumerate(sorted(glob, key=span, reverse=True)):
            # Own layer, starting at base+5 rather than base+1: the local routing
            # puts its support blocks at base+1, so a trunk there shared a plane
            # with them and picked up their signal — rule_mining measured the trunk
            # sitting at a constant 8 while the tower feeding it swung 0->15.
            # Layers stay 4k+1 so the source UP tower always climbs an even number
            # of torches (non-inverting), and step by 4 to keep planes isolated.
            self.net_trunk_y[n] = self.base_y + 5 + 4 * i
            row = free_rows.pop(0) if free_rows else None
            if row is None:
                res.failed.append(n)
                continue
            ok = self._one_global(n, row, res)
            (res.routed if ok else res.failed).append(n)
            if ok:
                res.trunk_rows[n] = row
        return res

    def _one_global(self, net: str, row: int, res: GlobalResult) -> bool:
        """Route one global net as TWO shielded modules.

        Upstream is a TrunkBox (source drive, climb, horizontal run, leg) and
        downstream a delivery box per sink. Both are verified sealed and with hostile
        geometry pressed against their shells, and their cascade is verified too, so
        emitting exactly those modules is what makes the module-level result match
        the bench result. The previous body wired the same path by hand across ten-odd
        boundaries and never got past 3/10.
        """
        ty = self.net_trunk_y[net]
        src = self.pl.net_sources[net]
        sinks = self.pl.net_sinks[net]
        # Transactional emit: everything goes to a LOCAL dict first, merged into
        # res.blocks only on success. A failure used to leave the trunk's blocks
        # behind (they were put directly), and the NEXT net's delivery-box check
        # then collided with the dead net's residue (measured: n7's box hit n3's
        # abandoned trunk at (13,17,*) after n3 failed on a later sink).
        local_blocks: Dict[Pos, str] = {}
        put = local_blocks.__setitem__
        base = self.base_y

        # one TrunkBox per net, running east far enough to reach the westmost sink
        # delivery, then turning onto this net's row
        first_sink_x = min(k[0] for k in sinks)
        run_to = max(src[0] + 6, first_sink_x - 24)
        # Choose the climb column dynamically. All source pins sit on x=0, so
        # fixed offsets put adjacent nets' ladders in the same column (measured:
        # n2's torch at (3,5,31) collided with n4's cross-leg repeater there).
        # The climb tower occupies (cx, y, sz) for y in base+1..plane, so pick
        # the first cx in src+2..src+6 whose tower cells are all free.
        climb_x = -1
        for cand in range(src[0] + 2, src[0] + 7):
            cells = [(cand, y, src[2]) for y in range(base + 1, ty + 1)]
            if all(self.box_vox.get(c) in (None, net) for c in cells) and \
               all(c not in res.blocks for c in cells):
                climb_x = cand
                break
        # LEG column: pick the first column east of the climb whose ENTIRE
        # vertical span (from the source's z to the corridor row) is free of
        # gate bodies. The climb column runs through the source's own gate row
        # and every row between it and the corridor (measured on Control: n16's
        # leg along x=24 hit gate bodies at z=53-55, 72-74, 91-93), so the leg
        # must jig to a gate-free column first.
        leg_x = -1
        z0l, z1l = sorted((src[2], row))
        # The leg must sit EAST of the climb: TrunkBox's climb-to-leg jog walks
        # cx -> leg_x (west-facing repeats), so a leg west of the climb was
        # never connected (measured: n2's leg_x=2 west of climb_x=5 left the
        # whole trunk dark past the climb top).
        for cand in range(max(src[0] + 2, climb_x + 1), src[0] + 26):
            if cand == climb_x:
                continue
            cols = [(cand, z) for z in range(z0l, z1l + 1)]
            if any(c in self.cell_xz or c in self.pin_xz for c in cols):
                continue
            # The leg walks on THIS net's trunk plane only (y=ty); other nets'
            # planes are isolated layers, so only same-plane conflicts matter.
            if any(self.box_vox.get((cand, ty, z)) not in (None, net)
                   for z in range(z0l, z1l + 1)):
                continue
            leg_x = cand
            break
        try:
            tb = TrunkBox(src_cell=(src[0], base, src[2]), plane=ty,
                          run_to_x=run_to, leg_to_z=row, climb_x=climb_x,
                          leg_x=leg_x)
        except AssertionError as _ae:
            print(f'  [{net}] TrunkBox ASSERT: {_ae}', flush=True)
            return False
        # The box's shell inevitably passes over the PI column and the first gate
        # column on its way out of the field. Rejecting the box for that would make
        # every global net unroutable (measured: 0 of 7). The shell is protective,
        # not load-bearing, so cells that would land on a pin or a gate body are
        # simply skipped — the interior, which carries the signal, is untouched.
        interior = {c for (c, b) in tb.blocks.items() if b != S}
        # in_cell sits ON the source pin by design (the box reads it), so it is an
        # interface, not an obstruction — counting it as a collision rejected every
        # global net (0 of 7) over a single cell.
        iface = {(tb.in_cell[0], tb.in_cell[2]), (tb.out_cell[0], tb.out_cell[2])}
        blocked = [c for c in tb.cells()
                   if c not in iface
                   and (c in self.cell_xz or c in self.pin_xz)
                   and any((c[0], y, c[1]) in interior
                           for y in range(tb.extent[0][1], tb.extent[1][1] + 1))]
        if blocked:
            print(f'  [{net}] trunk blocked={blocked[:3]}', flush=True)
            return False
        if any(self.box_vox.get(c) not in (None, net) for c in interior):
            print(f'  [{net}] trunk voxconf', flush=True)
            return False
        put_blocks = []
        for (bx, by, bz), bb in tb.blocks.items():
            if bb == S and ((bx, bz) in self.cell_xz or (bx, bz) in self.pin_xz):
                continue                      # skip shell over pins / gate bodies
            put((bx, by, bz), bb)
            put_blocks.append((bx, by, bz, bb))
        res.rmap.reserve(reservation_from_cells(
            f"{net}:trunk",
            put_blocks,
            "shielded trunk box"))
        for c in interior:
            self.box_vox[c] = net
        # reserve EVERY column the box touches (shell included): the local
        # router only sees the y0 projection of `reserved`, and it lays its own
        # bridge towers up to y=9 — without the shell columns it would drive a
        # tower straight through a global box's shell (measured: a local tower's
        # wall_torch landed inside n13:sink@93,21:box and its rungs overwrote the
        # box's shell stone).
        # Reserve only columns with blocks at y <= 9: the local router treats
        # reserved as y0-plane cell_xz, and the trunk's HIGH layers (y=25 wires)
        # were blocking whole local corridors that never came near them
        # (measured: n18's trunk column at (247,25,3..8) reserved (247,3..8),
        # sealing n21's descent stair at every offset). Local bridge towers top
        # out at y=9, so anything above that is invisible to them.
        for (bx, by, bz) in tb.blocks:
            if by <= 9:
                res.reserved.add((bx, bz))

        # each sink: a delivery box hung off the trunk's row.
        # prev_sink_cells tracks THIS net's earlier sinks' placed cells. Two of
        # this net's sinks' segments beside each other short in MC just like
        # foreign nets do (measured: n2's sink3 feed at (173,0,0) read 14 with
        # its source cut, driven by sink4's stair out at (173,0,-1) one cell
        # away). box_vox is keyed by net only, so it cannot distinguish this
        # net's own sinks — this set does.
        prev_sink_cells: Set[Pos] = set()
        foreign_pins = [p for n2, ps in self.pins_by_net.items()
                        for p in ps if n2 != net]
        for k in sinks:
            box = None
            # Deep drops need the TOWER: the staircase loses a level per level
            # dropped and was only measured delivering through 8, while the
            # tower regenerates at every rung (measured 4..28) and is far more
            # compact (a drop=21 stair sweeps 83 columns, the tower 24 — the
            # dense ALU field rejected every stair candidate for n3's
            # sink(120,0,19)). Shallow drops prefer the smaller stairs.
            kinds = (("tower", "stairs") if (ty - base) > STAIRS_MAX_DROP
                     else ("stairs", "tower"))
            for kind in kinds:
                for gap in (2, 3, 4, 5, 6):
                    # Mirror the tower to the z-1 side when a foreign pin sits
                    # on its z+2 flank: the tower's z+1..z+2 columns (A + torch
                    # + shell) would seal the neighbour's feed (measured: n18's
                    # tower sealed n21's feed (251,2)).
                    # Only pins under the tower's OWN x span matter: the
                    # delivery tower's shaft sits roughly k[0]-4..k[0]-1 (the
                    # out is gap cells west of the pin). A pin further east is
                    # outside the tower and must not trigger a mirror (measured:
                    # n13's (279,0) tower mirrored for the pin at (279,2) that
                    # sat beyond its shaft — and the mirrored tower's default
                    # state outputs 14, freezing the sink).
                    flip_arm = False
                    for _px in range(k[0] - 4, k[0]):
                        if self.pin_xz.get((_px, k[2] + 2)) not in (None, net):
                            flip_arm = True
                            break
                    for dz in (0, 1, -1, 2, -2):
                        cand, _kind = delivery_for_sink((k[0], k[2]), ty, base,
                                                        gap=gap, dz=dz,
                                                        prefer=kind,
                                                        flip_arm=flip_arm)
                        # Exact-cell conflict with gate bodies and pins. The old
                        # check was a height-blind column projection — it
                        # rejected a box whose SHELL passed 20 blocks above a
                        # pin while letting a box sit one cell from a foreign
                        # pin at GROUND level (measured on alu1: n3's drop=21
                        # stair swept z=19 from x=92..124 and every candidate
                        # died on pins its interior never got within 10 blocks
                        # of).
                        if any(c in self.occ_cells for c in cand.blocks):
                            continue
                        # Conduction range of FOREIGN pins: a conducting box
                        # cell at ground level within one cell of another net's
                        # pin is a real MC short (dust couples across one
                        # cell). This net's own pins are the target — the feed
                        # drives them by design. A box cell directly ABOVE a
                        # pin is caught by the exact-cell check above (its
                        # support would sit on the pin cell).
                        if any(b != S and c[1] == base and
                               any(abs(c[0] - p[0]) <= 1 and
                                   abs(c[2] - p[2]) <= 1 and p[1] == base
                                   for p in foreign_pins)
                               for c, b in cand.blocks.items()):
                            continue
                        # The box's SEAT cells (a stair's diagonal-down ceiling)
                        # must stay air: a foreign wire's support there blocks
                        # the stair's step (measured: sink1's leg support at
                        # (217,4,19) killed sink2's stair). The seats are not in
                        # the box's blocks, so check them explicitly against
                        # committed blocks and this net's earlier sink wires.
                        if any(c in res.blocks or c in prev_sink_cells
                               for c in cand.keep_air):
                            continue
                        dint = {c for (c, b) in cand.blocks.items() if b != S}
                        if any(self.box_vox.get(c) not in (None, net)
                               for c in dint):
                            continue
                        # Block-level overlap with ALREADY PLACED global blocks
                        # AND this net's own trunk (which lives in local_blocks
                        # until commit): a neighbour's tower TORCH landing on a
                        # shell cell overwrites it (measured: n18's tower foot
                        # (197,0,0) landed on its OWN trunk's shell because the
                        # transactional emit kept the trunk out of res.blocks
                        # during box selection).
                        if any(c in res.blocks for c in cand.blocks):
                            continue
                        # This net's OWN earlier sinks' segments: same-net
                        # adjacency is still a real MC short (different signal
                        # paths), unlike the trunk which is the same path and
                        # legally touches the box. Reject overlap AND
                        # 8-neighbourhood.
                        if any(c in prev_sink_cells for c in cand.blocks):
                            continue
                        if any(any((c[0]+_dx, c[1], c[2]+_dz) in prev_sink_cells
                                   for _dx, _dz in ((1,0),(-1,0),(0,1),(0,-1),
                                                    (1,1),(1,-1),(-1,1),(-1,-1)))
                               for c in cand.blocks):
                            continue
                        # FOREIGN nets' CONDUCTING blocks: the box's interior
                        # can sit beside a foreign wire and be driven by it
                        # even though the cells never overlap (measured: a
                        # stair's out read 13/14 with its input cut, fed by a
                        # neighbouring net's run wire one cell away). Shell
                        # stone does not conduct, so only non-stone neighbours
                        # matter.
                        if any(any(res.blocks.get((c[0]+_dx, c[1], c[2]+_dz))
                                   not in (None, S)
                                   for _dx, _dz in ((1,0),(-1,0),(0,1),(0,-1),
                                                    (1,1),(1,-1),(-1,1),(-1,-1)))
                               for c in cand.blocks):
                            continue
                        box = cand
                        break
                    if box is not None:
                        break
                if box is not None:
                    break
            if box is None:
                print(f'  [{net}] sink{k} no delivery box', flush=True)
                return False

            # Wire supports on the box's torch-top cells must be GLASS: a stone
            # support there is charged by the lit torch and leaks its strong
            # power into the wire above (measured: the tower's torch1 froze the
            # whole sink on at drive=0). Glass is a solid support (wire stays
            # placed) that does not conduct (measured in MCHPRS).
            def sup(x, y, z):
                put((x, y, z),
                    "minecraft:glass" if (x, y, z) in box.keep_glass else S)
            # run along this net's row from the trunk's out to the box's in, then
            # turn down the box's column — a single boundary between two shells
            ox, oy, oz = tb.out_cell
            ix, iy, iz = box.in_cell
            # Refresh every 12 cells: an unrefreshed run decays a level per cell
            # and died well before the box (measured: n4's 19-cell run from
            # (201,5,64) read 12 at the start, 3 at x=210, 0 at x=220). The
            # repeater faces west (travel is +x), placed BEFORE the wire so a
            # subsequent refresh reads it.
            # Start the counter at the refresh threshold so the FIRST run cell
            # is a repeater: the run's input is the leg's END, which arrives
            # already attenuated (measured: n3's leg delivered 8 at the row, and
            # a run starting from 8 decayed to 0 before its first refresh, so
            # the whole run after it stayed dark). Like _leg, re-drive at the
            # junction.
            run_n = 11
            for x in range(min(ox, ix), max(ox, ix) + 1):
                if self.box_vox.get((x, ty, oz)) not in (None, net) or \
                   (x, ty, oz) in res.blocks:
                    return False      # run would overwrite a foreign net's box/shell
                sup(x, ty - 1, oz)
                prev_sink_cells.add((x, ty - 1, oz))
                run_n += 1
                # The FIRST cell is the leg's END (the leg lands at (x,ty,oz)),
                # so it must be plain dust — a refresh repeater there reads
                # (x-1, ty, oz), which is empty (measured: n2's run start at
                # (6,17,73) read 0 with a full-strength leg one cell south).
                # The refresh starts one cell east, reading this cell.
                if run_n >= 12 and x != max(ox, ix) and x != min(ox, ix):
                    put((x, ty, oz), "minecraft:repeater[facing=west,delay=1]")
                    run_n = 0
                else:
                    put((x, ty, oz), W)
                self.box_vox[(x, ty, oz)] = net
                prev_sink_cells.add((x, ty, oz))
                if ty <= 9:
                    res.reserved.add((x, oz))
            if iz != oz:
                # The leg column ix can collide with this net's OWN trunk leg
                # (trunk leg_x is chosen independently of the box's x — measured
                # on n13: both landed on x=78 and the leg overwrote the trunk's
                # leg wire, 17 audit violations). Walk the leg on the first free
                # column near ix instead, then jog back at the bottom.
                lx = ix
                zlo, zhi = sorted((oz, iz))
                for cand in range(ix, ix + 8):
                    if all(self.box_vox.get((cand, ty, z)) in (None, net)
                           for z in range(zlo, zhi + 1)) and \
                       all((cand, ty, z) not in res.blocks
                           for z in range(zlo, zhi + 1)):
                        lx = cand
                        break
                self._leg(put, lx, oz, iz, res, net=net, ty=ty,
                         keep_glass=box.keep_glass,
                         prev_sink_cells=prev_sink_cells)
                # jog the leg back onto the box's column at the bottom (a short
                # +x wire at the same height, then the L below)
                if lx != ix:
                    for xx in range(lx, ix):
                        if (xx, ty, iz) in res.blocks:
                            return False
                        sup(xx, ty - 1, iz)
                        put((xx, ty, iz), W)
                        self.box_vox[(xx, ty, iz)] = net
                        prev_sink_cells.add((xx, ty, iz))
                        prev_sink_cells.add((xx, ty - 1, iz))
                        if ty <= 9:
                            res.reserved.add((xx, iz))
            # Feed the box's WEST-facing input repeater: it reads (ix-1, iz),
            # but the leg arrives from the north at (ix, iz) which the repeater
            # then occupies. An L-jog west then south puts a wire at (ix-1, iz)
            # connected to the leg (measured: n4's stairs in read an empty
            # (213,5,19) and the whole delivery stayed dark).
            if self.box_vox.get((ix - 1, ty, iz)) in (None, net):
                if iz + 1 <= self.z1 + 1:
                    # full L: (ix, iz+1) is the leg's last wire (the leg walks
                    # DOWN toward iz), jog west then south so the wire at
                    # (ix-1, iz) is fed by the leg
                    for jx, jz in ((ix - 1, iz + 1), (ix - 1, iz)):
                        # Only a FOREIGN interior blocks the L-jog. This net's own
                        # trunk shell at the corner is a legitimate cell to
                        # overwrite — the corner is the only way the leg feeds
                        # the box's west-facing input (measured: n3's corner
                        # (32,21,16) sat on its own trunk shell, the L-jog
                        # returned False, and the whole delivery stayed dark).
                        if self.box_vox.get((jx, ty, jz)) not in (None, net):
                            return False
                        sup(jx, ty - 1, jz)
                        put((jx, ty, jz), W)
                        self.box_vox[(jx, ty, jz)] = net
                        prev_sink_cells.add((jx, ty, jz))
                        prev_sink_cells.add((jx, ty - 1, jz))
                        if ty <= 9:
                            res.reserved.add((jx, jz))

            put_blocks = []
            for (bx, by, bz), bb in box.blocks.items():
                put((bx, by, bz), bb)
                put_blocks.append((bx, by, bz, bb))
                prev_sink_cells.add((bx, by, bz))
            res.rmap.reserve(reservation_from_cells(
                f"{net}:sink@{k[0]},{k[2]}:box",
                put_blocks,
                "shielded delivery box"))
            for c in dint:
                self.box_vox[c] = net
            for (bx, by, bz) in box.blocks:
                if by <= 9:
                    res.reserved.add((bx, bz))

            # the box's out drives the pin's feed cell. Walk EAST on the box's
            # own row to the pin column, THEN jog along z there. Jogging on the
            # out column (the old order) crossed the neighbouring net's tower
            # feet (measured: n3's jog at x=12 from z=15 to 17 wrote (12,0,17)
            # over n2's box shell); the pin column is clear by construction.
            bx2, by2, bz2 = box.out_cell
            # Feed run from the box's out to the pin's feed column (k[0]-1),
            # EITHER direction: the staircase's flat landings push `out` a
            # couple of cells past the computed anchor, so out can land EAST of
            # the feed (measured: n2's sink(174,19) box out at x=174 while the
            # feed is at 173 — a strictly-eastward range was empty and the feed
            # never got wired).
            lo, hi = sorted((bx2 + 1, k[0] - 1))
            for xx in range(lo, hi + 1):
                # The feed run walks y0 through possibly dense territory; a
                # foreign wire on the same layer one cell away is a real MC
                # short (measured: n2's feed (173,0,0) read 14 with its source
                # cut, driven by a neighbour's run wire at (173,0,-1)). The
                # wire itself is never placed beside a foreign interior
                # (box_vox checks that), but the run's 8-neighbourhood is not
                # checked anywhere — reject the placement instead of emitting a
                # silently-cross-talking net.
                for _dx, _dz in ((1, 0), (-1, 0), (0, 1), (0, -1),
                                 (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    _o = self.box_vox.get((xx + _dx, base, bz2 + _dz))
                    if _o is not None and _o != net:
                        return False
                put((xx, base, bz2), W)
                prev_sink_cells.add((xx, base, bz2))
                if ty <= 9:
                    res.reserved.add((xx, bz2))
            if bz2 != k[2]:
                zstep = 1 if k[2] > bz2 else -1
                for zz in range(bz2 + zstep, k[2] + zstep, zstep):
                    put((k[0] - 1, base, zz), W)
                    prev_sink_cells.add((k[0] - 1, base, zz))
                    if ty <= 9:
                        res.reserved.add((k[0] - 1, zz))

        res.wire_count = sum(1 for b in res.blocks.values() if b == W)
        res.blocks.update(local_blocks)
        return True

    def _leg(self, put, x, z_from, z_to, res, net=None, refresh=12, ty=None,
             keep_glass=frozenset(), prev_sink_cells=None):
        """A z-direction run on the trunk plane at column `x`, with a refresh
        repeater every `refresh` cells. Travel +z needs facing=north and -z needs
        facing=south (a repeater reads the side it faces — verified in
        test_rep_facing). Straight line, so the orientation is unambiguous."""
        ty = self.trunk_y if ty is None else ty
        if z_from == z_to:
            put((x, ty - 1, z_from),
                "minecraft:glass" if (x, ty - 1, z_from) in keep_glass else S)
            put((x, ty, z_from), W)
            if ty <= 9:
                res.reserved.add((x, z_from))
            return
        step = 1 if z_to > z_from else -1
        facing = "north" if step == 1 else "south"
        # Start the counter at the threshold so the FIRST cell after the junction
        # is a repeater. A leg branches off a trunk whose signal has already
        # attenuated (measured: 10 at the junction), so waiting the full 12 cells
        # let it reach 0 before the first refresh and the whole leg died.
        run = refresh
        z = z_from
        while True:
            if net is not None and (self.box_vox.get((x, ty, z)) not in (None, net)
                                    or (x, ty, z) in res.blocks):
                return False          # leg would overwrite a foreign net's box/shell
            put((x, ty - 1, z),
                "minecraft:glass" if (x, ty - 1, z) in keep_glass else S)
            if prev_sink_cells is not None:
                prev_sink_cells.add((x, ty - 1, z))
            run += 1
            if run >= refresh and z != z_to and z != z_from:
                put((x, ty, z),
                    f"minecraft:repeater[facing={facing},delay=1]")
                run = 0
            else:
                put((x, ty, z), W)
            if net is not None:
                self.box_vox[(x, ty, z)] = net
            if prev_sink_cells is not None:
                prev_sink_cells.add((x, ty, z))
            if ty <= 9:
                res.reserved.add((x, z))
            if z == z_to:
                break
            z += step

    # ---------- P3: local nets, per zone, avoiding the reservations ----------
    # 分区隔离：zone box = bounds ± margin，不同 zone 的 router 互相看不见对方
    # 布线 —— MCHPRS 实测 zone(1,0) 的 n14 wire (92,0,18) 与 zone(0,0) 的 n7
    # feed (92,0,19) 相邻串扰，而各 zone 独立计数 0（跨 zone 短路结构性漏检）。
    # 修复：迭代重布，把其他 zone 已布线的 wire 注入本 zone 的 occupancy（hard
    # blocker），直到跨 zone 短路=0。
    def route_locals(self, local: List[str], reserved: Set[XZ], rounds=2,
                     global_vox: Dict[Pos, str] = None,
                     isolation_passes: int = 4):
        by_zone: Dict[tuple, List[str]] = {}
        for n in local:
            s = self.pl.net_sources[n]
            by_zone.setdefault(self._zone(s[0], s[2]), []).append(n)
        zones = sorted(by_zone.items())
        wires_by_zone: Dict[tuple, Set[XZ]] = {z: set() for z, _ in zones}
        best = None
        best_key = None
        for _pass in range(isolation_passes):
            out = []
            this_pass: Dict[tuple, Set[XZ]] = {z: set() for z, _ in zones}
            for z, nets in zones:
                sub = copy.copy(self.pl)
                sub.net_sinks = {n: self.pl.net_sinks[n] for n in nets}
                sub.net_sources = {n: self.pl.net_sources[n] for n in nets}
                # the trunk columns are occupied ground for the plane router
                sub.occupancy = set(self.pl.occupancy) | \
                    {(x, self.base_y, zz) for (x, zz) in reserved}
                # 分区隔离带：zone 边界两侧 1 格禁布，跨 zone 相邻在物理上
                # 不可能（双方都离边界 >= 1 格，最小间距 2 格）。
                # zone box 也限制到本 zone 范围 ± margin，线不越界乱跑。
                xa, za = z
                wx0, wx1 = xa * self.W, (xa + 1) * self.W
                wz0, wz1 = za * self.Wz, (za + 1) * self.Wz
                # 只禁边界外侧 1 格列/行：本 zone 线止于 wx1-1，邻 zone 线始于
                # wx1+1，最小间距 2 格 → 跨 zone 相邻在物理上不可能。
                for gz in range(wz0 - 1, wz1 + 2):
                    for gx in (wx0 - 1, wx1):
                        sub.occupancy.add((gx, self.base_y, gz))
                for gx in range(wx0 - 1, wx1 + 2):
                    for gz in (wz0 - 1, wz1):
                        sub.occupancy.add((gx, self.base_y, gz))
                sub.bounds = ((wx0 - 16, self.base_y, wz0 - 16),
                              (min(wx1 + 16, self.pl.bounds[1][0]),
                               self.pl.bounds[1][1],
                               min(wz1 + 16, self.pl.bounds[1][2])))
                # OTHER zones' wires (previous pass's full set + this pass's
                # earlier zones) are hard blockers — but never this zone's own
                # wires: it re-lays them from scratch each pass.
                for z2 in this_pass:
                    if z2 != z:
                        for (fx, fz) in (wires_by_zone[z2] | this_pass[z2]):
                            sub.occupancy.add((fx, self.base_y, fz))
                r = BuildableRouter(sub, margin=16, global_vox=global_vox)
                rr = r.route(verbose=False, max_rounds=rounds)
                sh, _ = r._count_shorts(rr)
                out.append((z, nets, rr, sh))
                w: Set[XZ] = set()
                for n in nets:
                    for p in rr.wires.get(n, ()):
                        w.add((p[0], p[2]))
                    for (pos, _f) in rr.repeaters.get(n, ()):
                        w.add((pos[0], pos[2]))
                this_pass[z] = w
            cross = self._cross_zone_shorts(out)
            wires_by_zone = this_pass
            key = (cross,
                   sum(s for _z, _n, _rr, s in out),
                   -sum(len(n) - len(rr.failed) for _z, n, rr, _s in out))
            if best_key is None or key < best_key:
                best_key = key
                best = out
            if cross == 0 and all(s == 0 for _z, _n, _rr, s in out) \
                    and all(not rr.failed for _z, _n, rr, _s in out):
                return out
        return best

    def _cross_zone_shorts(self, out):
        """Merge every zone's wire/repeater ownership and count foreign
        8-neighbourhood pairs ACROSS zones (each zone's own counter cannot see
        the neighbours' wires in the margin-overlap band). Also counts a cell
        owned by two different nets (overlap)."""
        owner: Dict[Pos, str] = {}
        rep_face: Dict[Pos, str] = {}
        overlap = 0
        for _z, _nets, rr, _sh in out:
            for p, o in rr.wire_owner.items():
                if p in owner and owner[p] != o:
                    overlap += 1
                owner[p] = o
            for net, reps in (rr.repeaters or {}).items():
                for (pos, f) in reps:
                    if pos in owner and owner[pos] != net:
                        overlap += 1
                    owner[pos] = net
                    rep_face[pos] = f
        _REP_AXIS = {"west": {(1, 0), (-1, 0)}, "east": {(1, 0), (-1, 0)},
                     "north": {(0, 1), (0, -1)}, "south": {(0, 1), (0, -1)}}

        def couples(a, b, off):
            if a in rep_face and off not in _REP_AXIS[rep_face[a]]:
                return False
            boff = (-off[0], -off[1])
            if b in rep_face and boff not in _REP_AXIS[rep_face[b]]:
                return False
            return True
        seen = set()
        for (x, y, z), net in owner.items():
            for dx, dz in _PLANE_SHELL:
                q = (x + dx, y, z + dz)
                o = owner.get(q)
                if o is not None and o != net and couples((x, y, z), q, (dx, dz)):
                    seen.add(tuple(sorted([(x, y, z), q])))
            for dy in (1, -1):
                q = (x, y + dy, z)
                o = owner.get(q)
                if o is not None and o != net:
                    seen.add(tuple(sorted([(x, y, z), q])))
        return len(seen) + overlap

    # ---------- driver ----------
    def run(self, rounds=2, verbose=True):
        t0 = time.time()
        nets, local, glob = self.classify()
        g = self.build_globals(glob)
        zres = self.route_locals(local, g.reserved, rounds=rounds,
                                 global_vox={p: f"g:{gv}"
                                              for p, gv in g.blocks.items()})
        loc_ok = sum(len(nets) - len(rr.failed) for _z, nets, rr, _s in zres)
        loc_short = sum(s for *_x, s in zres)
        cross_short = self._cross_zone_shorts(zres)
        loc_wire = sum(rr.total_wires() for _z, _n, rr, _s in zres)
        if verbose:
            print(f"  global: {len(g.routed)}/{len(glob)} routed, "
                  f"{len(g.blocks)} blocks, rows={len(g.trunk_rows)}")
            print(f"  local : {loc_ok}/{len(local)} routed over {len(zres)} zones, "
                  f"shorts={loc_short} wires={loc_wire}")
        return {
            "nets": len(nets), "local": len(local), "global": len(glob),
            "global_routed": len(g.routed), "global_failed": g.failed[:8],
            "local_routed": loc_ok, "local_shorts": loc_short,
            "cross_shorts": cross_short,
            "total_routed": len(g.routed) + loc_ok,
            "global_blocks": len(g.blocks), "local_wires": loc_wire,
            "secs": round(time.time() - t0, 1),
        }, g, zres


def route_adaptive(placement, rounds=2, verbose=False,
                   grid=((96, 192), (64, 128), (48, 96), (32, 64),
                         (24, 48), (16, 32), (12, 24))):
    """Search zone granularity from COARSE to FINE and stop at the first setting
    that routes every net with zero shorts.

    Rationale from the diagnosis: every failure ever observed had the same cause —
    a connection long enough to need a clear channel was classified `local` because
    the zone was big enough to contain it, so it had to fight for a plane that was
    already full. Global nets, which get a dedicated corridor, never failed (100%
    in every module). Finer zones promote more nets to global and fix the failures;
    coarser zones keep more nets on the cheap local plane and use less space.
    Searching coarse->first-success therefore yields the SMALLEST layout that still
    routes completely, instead of hard-coding one granularity per module.

    Returns (report, router, global_result, zone_results).
    """
    best = None
    for (W, Wz) in grid:
        r = GlobalFirstRouter(placement, zone_width=W, zone_depth=Wz)
        rep, g, zres = r.run(rounds=rounds, verbose=False)
        rep["zone_width"], rep["zone_depth"] = W, Wz
        complete = (rep["total_routed"] == rep["nets"]
                    and rep["local_shorts"] == 0
                    and rep.get("cross_shorts", 0) == 0)
        if verbose:
            print(f"    W={W:3d} Wz={Wz:3d}: routed {rep['total_routed']}/{rep['nets']} "
                  f"local={rep['local']} global={rep['global']} "
                  f"shorts={rep['local_shorts']}"
                  f"{'  <= complete' if complete else ''}", flush=True)
        if best is None or (rep["total_routed"], -rep["local_shorts"]) > \
                (best[0]["total_routed"], -best[0]["local_shorts"]):
            best = (rep, r, g, zres)
        if complete:
            return rep, r, g, zres
    return best


def main():
    from placer import place
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    if "--adaptive" in sys.argv:
        mods = [a for a in sys.argv[1:]
                if not a.isdigit() and not a.startswith("-")] or list(nls.keys())
        print(f"{'module':12s} {'gates':>5s} {'W':>4s} {'Wz':>4s} "
              f"{'local':>5s} {'glob':>5s} {'routed':>9s} {'short':>5s} {'secs':>6s}")
        for mod in mods:
            pl = place(nls[mod], col_gap=16, row_gap=16)
            rep, _r, _g, _z = route_adaptive(pl, verbose="-v" in sys.argv)
            done = "OK" if rep["total_routed"] == rep["nets"] \
                           and rep["local_shorts"] == 0 else "INCOMPLETE"
            print(f"{mod:12s} {len(nls[mod]['cells']):5d} {rep['zone_width']:4d} "
                  f"{rep['zone_depth']:4d} {rep['local']:5d} {rep['global']:5d} "
                  f"{str(rep['total_routed'])+'/'+str(rep['nets']):>9s} "
                  f"{rep['local_shorts']:5d} {rep['secs']:6.1f}  {done}", flush=True)
        return
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or ["alu1"]
    zw = next((int(a) for a in sys.argv[1:] if a.isdigit()), 64)
    for mod in mods:
        pl = place(nls[mod], col_gap=16, row_gap=16)
        r = GlobalFirstRouter(pl, zone_width=zw)
        print(f"[{mod} W={zw}]")
        rep, _g, _z = r.run()
        print(f"  => total routed {rep['total_routed']}/{rep['nets']} "
              f"(global {rep['global_routed']}/{rep['global']}, "
              f"local {rep['local_routed']}/{rep['local']}) "
              f"local_shorts={rep['local_shorts']} {rep['secs']}s")


if __name__ == "__main__":
    main()
