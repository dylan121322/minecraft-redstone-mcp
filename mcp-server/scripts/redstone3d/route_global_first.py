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
from delivery_box import delivery_for_sink
from trunk_box import TrunkBox

Pos = Tuple[int, int, int]
XZ = Tuple[int, int]
W = "minecraft:redstone_wire"; S = "minecraft:stone"

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
        for cand in range(src[0] + 2, src[0] + 26):
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
        for (bx, _by, bz) in tb.blocks:
            res.reserved.add((bx, bz))

        # each sink: a delivery box hung off the trunk's row.
        # prev_sink_cells tracks THIS net's earlier sinks' placed cells. Two of
        # this net's sinks' segments beside each other short in MC just like
        # foreign nets do (measured: n2's sink3 feed at (173,0,0) read 14 with
        # its source cut, driven by sink4's stair out at (173,0,-1) one cell
        # away). box_vox is keyed by net only, so it cannot distinguish this
        # net's own sinks — this set does.
        prev_sink_cells: Set[Pos] = set()
        for k in sinks:
            box = None
            for gap in (2, 3, 4, 5, 6):
                for dz in (0, 1, -1, 2, -2):
                    cand, _kind = delivery_for_sink((k[0], k[2]), ty, base,
                                                    gap=gap, dz=dz)
                    cols = cand.cells()
                    if any(c in self.cell_xz or c in self.pin_xz for c in cols):
                        continue
                    dint = {c for (c, b) in cand.blocks.items() if b != S}
                    if any(self.box_vox.get(c) not in (None, net) for c in dint):
                        continue
                    # Block-level overlap with ALREADY PLACED global blocks AND
                    # this net's own trunk (which lives in local_blocks until
                    # commit): a neighbour's tower TORCH landing on a shell cell
                    # overwrites it (measured: n18's tower foot (197,0,0) landed
                    # on its OWN trunk's shell because the transactional emit
                    # kept the trunk out of res.blocks during box selection).
                    if any(c in res.blocks for c in cand.blocks):
                        continue
                    # This net's OWN earlier sinks' segments: same-net adjacency
                    # is still a real MC short (different signal paths), unlike
                    # the trunk which is the same path and legally touches the
                    # box. Reject overlap AND 8-neighbourhood.
                    if any(c in prev_sink_cells for c in cand.blocks):
                        continue
                    if any(any((c[0]+_dx, c[1], c[2]+_dz) in prev_sink_cells
                               for _dx, _dz in ((1,0),(-1,0),(0,1),(0,-1),
                                                (1,1),(1,-1),(-1,1),(-1,-1)))
                           for c in cand.blocks):
                        continue
                    # FOREIGN nets' CONDUCTING blocks: the box's interior can
                    # sit beside a foreign wire and be driven by it even though
                    # the cells never overlap (measured: a stair's out read
                    # 13/14 with its input cut, fed by a neighbouring net's run
                    # wire one cell away). Shell stone does not conduct, so only
                    # non-stone neighbours matter.
                    if any(any(res.blocks.get((c[0]+_dx, c[1], c[2]+_dz)) not in (None, S)
                               for _dx, _dz in ((1,0),(-1,0),(0,1),(0,-1),
                                                (1,1),(1,-1),(-1,1),(-1,-1)))
                           for c in cand.blocks):
                        continue
                    box = cand
                    box_dz = dz
                    break
            if box is None:
                print(f'  [{net}] sink{k} no delivery box', flush=True)
                return False

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
                put((x, ty - 1, oz), S)
                run_n += 1
                if run_n >= 12 and x != max(ox, ix):
                    put((x, ty, oz), "minecraft:repeater[facing=west,delay=1]")
                    run_n = 0
                else:
                    put((x, ty, oz), W)
                self.box_vox[(x, ty, oz)] = net
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
                self._leg(put, lx, oz, iz, res, net=net, ty=ty)
                # jog the leg back onto the box's column at the bottom (a short
                # +x wire at the same height, then the L below)
                if lx != ix:
                    for xx in range(lx, ix):
                        if (xx, ty, iz) in res.blocks:
                            return False
                        put((xx, ty - 1, iz), S)
                        put((xx, ty, iz), W)
                        self.box_vox[(xx, ty, iz)] = net
                        res.reserved.add((xx, iz))
            # Feed the box's WEST-facing input repeater: it reads (ix-1, iz),
            # but the leg arrives from the north at (ix, iz) which the repeater
            # then occupies. An L-jog west then south puts a wire at (ix-1, iz)
            # connected to the leg (measured: n4's stairs in read an empty
            # (213,5,19) and the whole delivery stayed dark).
            if (ix - 1, iz) not in res.blocks and \
               self.box_vox.get((ix - 1, ty, iz)) in (None, net):
                if iz + 1 <= self.z1 + 1:
                    # full L: (ix, iz+1) is the leg's last wire (the leg walks
                    # DOWN toward iz), jog west then south so the wire at
                    # (ix-1, iz) is fed by the leg
                    for jx, jz in ((ix - 1, iz + 1), (ix - 1, iz)):
                        if (jx, ty, jz) in res.blocks:
                            return False   # L-jog would overwrite a foreign shell
                        put((jx, ty - 1, jz), S)
                        put((jx, ty, jz), W)
                        self.box_vox[(jx, ty, jz)] = net
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
            for (bx, _by, bz) in box.blocks:
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
                res.reserved.add((xx, bz2))
            if bz2 != k[2]:
                zstep = 1 if k[2] > bz2 else -1
                for zz in range(bz2 + zstep, k[2] + zstep, zstep):
                    put((k[0] - 1, base, zz), W)
                    prev_sink_cells.add((k[0] - 1, base, zz))
                    res.reserved.add((k[0] - 1, zz))

        res.wire_count = sum(1 for b in res.blocks.values() if b == W)
        res.blocks.update(local_blocks)
        return True

    def _leg(self, put, x, z_from, z_to, res, net=None, refresh=12, ty=None):
        """A z-direction run on the trunk plane at column `x`, with a refresh
        repeater every `refresh` cells. Travel +z needs facing=north and -z needs
        facing=south (a repeater reads the side it faces — verified in
        test_rep_facing). Straight line, so the orientation is unambiguous."""
        ty = self.trunk_y if ty is None else ty
        if z_from == z_to:
            put((x, ty - 1, z_from), S)
            put((x, ty, z_from), W)
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
            put((x, ty - 1, z), S)
            run += 1
            if run >= refresh and z != z_to and z != z_from:
                put((x, ty, z),
                    f"minecraft:repeater[facing={facing},delay=1]")
                run = 0
            else:
                put((x, ty, z), W)
            if net is not None:
                self.box_vox[(x, ty, z)] = net
            res.reserved.add((x, z))
            if z == z_to:
                break
            z += step

    # ---------- P3: local nets, per zone, avoiding the reservations ----------
    def route_locals(self, local: List[str], reserved: Set[XZ], rounds=2,
                     global_vox: Dict[Pos, str] = None):
        by_zone: Dict[tuple, List[str]] = {}
        for n in local:
            s = self.pl.net_sources[n]
            by_zone.setdefault(self._zone(s[0], s[2]), []).append(n)
        out = []
        for z, nets in sorted(by_zone.items()):
            sub = copy.copy(self.pl)
            sub.net_sinks = {n: self.pl.net_sinks[n] for n in nets}
            sub.net_sources = {n: self.pl.net_sources[n] for n in nets}
            # the trunk columns are occupied ground for the plane router
            sub.occupancy = set(self.pl.occupancy) | \
                {(x, self.base_y, zz) for (x, zz) in reserved}
            r = BuildableRouter(sub, margin=16, global_vox=global_vox)
            rr = r.route(verbose=False, max_rounds=rounds)
            sh, _ = r._count_shorts(rr)
            out.append((z, nets, rr, sh))
        return out

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
        complete = (rep["total_routed"] == rep["nets"] and rep["local_shorts"] == 0)
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
