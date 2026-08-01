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
        put = res.blocks.__setitem__
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
            if all(self.box_vox.get(c) in (None, net) for c in cells):
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
            if any(self.box_vox.get((cand, y, z)) not in (None, net)
                   for z in range(z0l, z1l + 1) for y in range(base + 1, ty + 1)):
                continue
            leg_x = cand
            break
        try:
            tb = TrunkBox(src_cell=(src[0], base, src[2]), plane=ty,
                          run_to_x=run_to, leg_to_z=row, climb_x=climb_x,
                          leg_x=leg_x)
        except AssertionError:
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
            return False
        if any(self.box_vox.get(c) not in (None, net) for c in interior):
            return False
        for (bx, by, bz), bb in tb.blocks.items():
            if bb == S and ((bx, bz) in self.cell_xz or (bx, bz) in self.pin_xz):
                continue                      # skip shell over pins / gate bodies
            put((bx, by, bz), bb)
        res.rmap.reserve(reservation_from_cells(
            f"{net}:trunk",
            [(bx, by, bz, bb) for (bx, by, bz), bb in tb.blocks.items()],
            "shielded trunk box"))
        for c in interior:
            self.box_vox[c] = net
            res.reserved.add((c[0], c[2]))

        # each sink: a delivery box hung off the trunk's row
        for k in sinks:
            box = None
            for gap in (2, 3, 4, 5, 6):
                cand, _kind = delivery_for_sink((k[0], k[2]), ty, base, gap=gap)
                cols = cand.cells()
                if any(c in self.cell_xz or c in self.pin_xz for c in cols):
                    continue
                dint = {c for (c, b) in cand.blocks.items() if b != S}
                if any(self.box_vox.get(c) not in (None, net) for c in dint):
                    continue
                box = cand
                break
            if box is None:
                return False

            # run along this net's row from the trunk's out to the box's in, then
            # turn down the box's column — a single boundary between two shells
            ox, oy, oz = tb.out_cell
            ix, iy, iz = box.in_cell
            for x in range(min(ox, ix), max(ox, ix) + 1):
                put((x, ty - 1, oz), S)
                put((x, ty, oz), W)
                res.reserved.add((x, oz))
            if iz != oz:
                self._leg(put, ix, oz, iz, res, ty=ty)

            for (bx, by, bz), bb in box.blocks.items():
                put((bx, by, bz), bb)
            res.rmap.reserve(reservation_from_cells(
                f"{net}:sink@{k[0]},{k[2]}:box",
                [(bx, by, bz, bb) for (bx, by, bz), bb in box.blocks.items()],
                "shielded delivery box"))
            for c in dint:
                self.box_vox[c] = net
                res.reserved.add((c[0], c[2]))

            # the box's out drives the pin's feed cell
            bx2, by2, bz2 = box.out_cell
            for xx in range(bx2 + 1, k[0]):
                put((xx, base, bz2), W)
                res.reserved.add((xx, bz2))

        res.wire_count = sum(1 for b in res.blocks.values() if b == W)
        return True

    def _leg(self, put, x, z_from, z_to, res, refresh=12, ty=None):
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
            put((x, ty - 1, z), S)
            run += 1
            if run >= refresh and z != z_to and z != z_from:
                put((x, ty, z),
                    f"minecraft:repeater[facing={facing},delay=1]")
                run = 0
            else:
                put((x, ty, z), W)
            res.reserved.add((x, z))
            if z == z_to:
                break
            z += step

    # ---------- P3: local nets, per zone, avoiding the reservations ----------
    def route_locals(self, local: List[str], reserved: Set[XZ], rounds=2):
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
            r = BuildableRouter(sub, margin=16)
            rr = r.route(verbose=False, max_rounds=rounds)
            sh, _ = r._count_shorts(rr)
            out.append((z, nets, rr, sh))
        return out

    # ---------- driver ----------
    def run(self, rounds=2, verbose=True):
        t0 = time.time()
        nets, local, glob = self.classify()
        g = self.build_globals(glob)
        zres = self.route_locals(local, g.reserved, rounds=rounds)
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
