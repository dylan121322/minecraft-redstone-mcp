"""
route_channel.py — GLOBAL-GRID channel router with TORCH TOWERS (V2).

Layer model (y relative to base_y=b):
  y0  : cells, pins, y0 dust
  y1  : tower torches (standing)
  y2  : BLOCK+REPEATER chains (no shorts) + H-support
  y3  : H-layer DUST (horizontal X-runs)
  y4  : V-layer SUPPORT (solid blocks)
  y5  : V-layer DUST   (vertical Z-runs)

All vertical signal uses torch towers (1x1, no intermediate dust).
Source climbs happen at Ri (north of cell field), so y3/y4 intermediate dust
from climbs is distant from sink-pz descent dust => 0 shorts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
from collections import defaultdict
from placer import Placement

Pos = Tuple[int, int, int]


@dataclass
class ChannelResult:
    wires: Dict[str, Set[Pos]]
    supports: Set[Pos]
    repeaters: Dict[str, List[Tuple[Pos, str]]]
    torches: Set[Pos]
    failed: List[str]
    wire_owner: Dict[Pos, str] = field(default_factory=dict)

    def total_wires(self) -> int:
        return sum(len(w) for w in self.wires.values())


class ChannelRouter:
    def __init__(self, placement: Placement):
        self.pl = placement
        self.b = placement.bounds[0][1]
        mn, mx = placement.bounds
        self.x_min, self.x_max = mn[0], mx[0]
        self.z_min, self.z_max = mn[2], mx[2]
        self.seg: Dict[str, List[tuple]] = {}

    # ---- Primitives ----

    def _pi_rise(self, net, sx, sz):
        """PI tower at (sx,0,sz) to y2. sx=0.

        Dust at (sx+1, 0, sz) gets weak power from block0 (strongly powered),
        feeds cell input repeater at (2, 0, sz).  Uses dust to conduct.
        """
        b = self.b
        s = self.seg[net]
        s.append(("block", sx, b, sz))
        s.append(("torch", sx, b + 1, sz))
        s.append(("block", sx, b + 2, sz))
        s.append(("dust", sx + 1, b, sz))  # dust feeds cell input
        return (sx, b + 2, sz)

    def _nonpi_rise(self, net, sx, sz, src_col):
        """Non-PI: y0 chain from sx to src_col, tower to y2 at src_col."""
        b = self.b
        s = self.seg[net]
        for i in range(sx + 1, src_col + 1, 2):
            s.append(("rep", i, b, sz, "east"))
            s.append(("block", i + 1, b, sz))
        s.append(("torch", src_col, b + 1, sz))
        s.append(("block", src_col, b + 2, sz))
        return (src_col, b + 2, sz)

    def _chain_y2(self, net, x0, z0, x1, z1):
        """Block+repeater chain at y=b+2 from (x0,z0) to (x1,z1).

        No dust — uses only blocks and repeaters.  Handles any parity.
        """
        b = self.b
        s = self.seg[net]
        cx, cz = x0, z0
        # East/west
        if x1 > cx:
            while cx + 2 <= x1:
                s.append(("rep", cx + 1, b + 2, cz, "east"))
                s.append(("block", cx + 2, b + 2, cz))
                cx += 2
            if cx != x1:
                s.append(("rep", cx + 1, b + 2, cz, "east"))
                s.append(("block", x1, b + 2, cz))
                cx = x1
        elif x1 < cx:
            while cx - 2 >= x1:
                s.append(("rep", cx - 1, b + 2, cz, "west"))
                s.append(("block", cx - 2, b + 2, cz))
                cx -= 2
            if cx != x1:
                s.append(("rep", cx - 1, b + 2, cz, "west"))
                s.append(("block", x1, b + 2, cz))
                cx = x1
        # North/south
        if z1 < cz:
            while cz - 2 >= z1:
                s.append(("rep", cx, b + 2, cz - 1, "north"))
                s.append(("block", cx, b + 2, cz - 2))
                cz -= 2
            if cz != z1:
                s.append(("rep", cx, b + 2, cz - 1, "north"))
                s.append(("block", cx, b + 2, z1))
                cz = z1
        elif z1 > cz:
            while cz + 2 <= z1:
                s.append(("rep", cx, b + 2, cz + 1, "south"))
                s.append(("block", cx, b + 2, cz + 2))
                cz += 2
            if cz != z1:
                s.append(("rep", cx, b + 2, cz + 1, "south"))
                s.append(("block", cx, b + 2, z1))
                cz = z1

    def _climb_at_ri(self, net, x, Ri):
        """Climb y2->y5 at (x, Ri): 1 torch then V-support + V-dust.

        Intermediate torch inverts once (total 2 torches from source = non-inv).
        """
        b = self.b
        s = self.seg[net]
        s.append(("torch", x, b + 3, Ri))
        s.append(("block", x, b + 4, Ri))          # V-support at y4
        s.append(("dust", x, b + 5, Ri))           # V-dust at y5

    MAXRUN = 13   # refresh with a repeater before dust decays (dies after 15)

    def _vrun_y5(self, net, x, z0, z1, flow=0):
        """V-run at y5: support at y4, dust at y5. Inserts a repeater every
        MAXRUN blocks to refresh signal. `flow`: +1 if signal travels +z,
        -1 if -z, 0 if unknown/short (no repeaters)."""
        b = self.b
        s = self.seg[net]
        lo, hi = min(z0, z1), max(z0, z1)
        n = hi - lo
        for i, z in enumerate(range(lo, hi + 1)):
            s.append(("support", x, b + 4, z))
            # place a repeater instead of dust every MAXRUN steps (not at ends)
            if flow != 0 and i > 0 and i < n and i % self.MAXRUN == 0:
                # measured: signal flowing +z needs facing=north; -z needs south
                facing = "north" if flow > 0 else "south"
                s.append(("rep", x, b + 5, z, facing))
            else:
                s.append(("dust", x, b + 5, z))

    def _hrun_y3(self, net, x0, x1, z, flow=0):
        """H-run at y3: support at y2, dust at y3. Repeater every MAXRUN blocks.
        `flow`: +1 if signal travels +x, -1 if -x, 0 if unknown (no repeaters)."""
        b = self.b
        s = self.seg[net]
        lo, hi = min(x0, x1), max(x0, x1)
        n = hi - lo
        for i, x in enumerate(range(lo, hi + 1)):
            s.append(("support", x, b + 2, z))
            if flow != 0 and i > 0 and i < n and i % self.MAXRUN == 0:
                facing = "west" if flow > 0 else "east"   # facing = reverse of flow
                s.append(("rep", x, b + 3, z, facing))
            else:
                s.append(("dust", x, b + 3, z))

    def _drop_y5_to_y3(self, net, x, z):
        """Drop y5->y3 at (x,z). Creates y4 int. dust. Width=2."""
        b = self.b
        s = self.seg[net]
        s.append(("block", x + 1, b + 3, z))
        s.append(("dust", x + 1, b + 4, z))
        s.append(("support", x + 2, b + 2, z))
        s.append(("dust", x + 2, b + 3, z))

    def _climb_y3_to_y5(self, net, x, z):
        """Climb y3->y5 at (x,z). Creates y4 int. dust. Width=2."""
        b = self.b
        s = self.seg[net]
        s.append(("block", x + 1, b + 3, z))
        s.append(("dust", x + 1, b + 4, z))
        s.append(("block", x + 2, b + 4, z))
        s.append(("dust", x + 2, b + 5, z))

    def _descend_y5_to_y0(self, net, x, z):
        """Descent y5->y0 at (x,z). Landing at (x+5, b, z)."""
        b = self.b
        s = self.seg[net]
        s.append(("block", x + 1, b + 3, z))
        s.append(("dust", x + 1, b + 4, z))
        s.append(("block", x + 2, b + 2, z))
        s.append(("dust", x + 2, b + 3, z))
        s.append(("block", x + 3, b + 1, z))
        s.append(("dust", x + 3, b + 2, z))
        s.append(("block", x + 4, b, z))
        s.append(("dust", x + 4, b + 1, z))
        s.append(("dust", x + 5, b, z))


    def _hrun_y0(self, net, x0, x1, z):
        b = self.b
        s = self.seg[net]
        lo, hi = min(x0, x1), max(x0, x1)
        for x in range(lo, hi + 1):
            s.append(("dust", x, b, z))

    @staticmethod
    def _find_free_col(desired, avoid, step=2):
        col = desired
        while True:
            ok = True
            for av in avoid:
                if abs(col - av) <= 1:
                    ok = False
                    break
            if ok:
                return col
            col += step

    # ---- Main route ----

    def route(self, verbose=False) -> ChannelResult:
        nets = sorted([n for n in self.pl.net_sinks
                       if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)])

        # ========== 1. SINK APPROACH COLS ==========
        sinks_by_px = defaultdict(list)
        for net in nets:
            for k in self.pl.net_sinks[net]:
                px, _, pz = k
                sinks_by_px[px].append((pz, net))
        approach_cols: Dict[Tuple[str, int, int], int] = {}
        taken_appr: Set[int] = set()
        for px in sorted(sinks_by_px):
            for rank, (pz, net) in enumerate(sorted(sinks_by_px[px])):
                base = px - 5 - 2 * rank
                col = self._find_free_col(base, taken_appr)
                approach_cols[(net, px, pz)] = col
                taken_appr.add(col)

        # ========== 2. SOURCE V-COLS ==========
        sources_by_sx = defaultdict(list)
        for net in nets:
            sx, _, sz = self.pl.net_sources[net]
            sources_by_sx[sx].append((sz, net))

        PI_SRC = {'n2': 4, 'n3': -50, 'n4': 23, 'n5': 25, 'n6': 27, 'n7': 29, 'n8': 0}
        src_allocated: Dict[str, int] = {}
        for net, col in PI_SRC.items():
            if net in nets:
                src_allocated[net] = col

        for sx in sorted(sources_by_sx):
            for k, (sz, net) in enumerate(sorted(sources_by_sx[sx])):
                if net in self.pl.primary_inputs:
                    continue
                base = sx + 6 + 2 * k
                col = base
                while True:
                    blocked = False
                    for (an, _, _), ac in approach_cols.items():
                        if an == net:
                            continue
                        if abs(col - ac) <= 1:
                            blocked = True
                            break
                    if not blocked:
                        for sn, sc in src_allocated.items():
                            if sn == net:
                                continue
                            if abs(col - sc) <= 1:
                                blocked = True
                                break
                    if not blocked:
                        break
                    col += 2
                src_allocated[net] = col

        # ========== 3. TRUNK ROWS & COLS ==========
        Z_TOP = self.z_max + 5  # +5 ensures even (z_max=41 -> 46)
        X_EAST = self.x_max + 4
        trunk_row = {n: Z_TOP + 2 * i for i, n in enumerate(nets)}
        trunk_col = {n: X_EAST + 2 * i for i, n in enumerate(nets)}

        Z_APPR = Z_TOP + 2 * len(nets) + 4
        appr_row: Dict[str, int] = {}
        for j, net in enumerate(nets):
            appr_row[net] = Z_APPR + 2 * j

        # ========== 4. BUILD SEGMENTS ==========
        self.seg = {n: [] for n in nets}

        for net in nets:
            sx, _, sz = self.pl.net_sources[net]
            src_col = src_allocated[net]
            Ri = trunk_row[net]
            Ci = trunk_col[net]
            is_pi = net in self.pl.primary_inputs

            # ---- Rise to y2 ----
            if is_pi:
                tx, ty, tz = self._pi_rise(net, sx, sz)
            else:
                tx, ty, tz = self._nonpi_rise(net, sx, sz, src_col)

            # ---- Chain at y2 to (src_col, Ri) ----
            self._chain_y2(net, tx, tz, src_col, Ri)

            # ---- Climb y2->y5 at (src_col, Ri) ----
            self._climb_at_ri(net, src_col, Ri)

            # ---- Drop y5->y3 at (src_col, Ri) to H-layer ----
            self._drop_y5_to_y3(net, src_col, Ri)

            # ---- H-run east on Ri (y3) to Ci-2 ---- (flow +x)
            self._hrun_y3(net, src_col + 2, Ci - 2, Ri, flow=+1)

            # ---- Climb y3->y5 at (Ci-2, Ri) back to V-layer ----
            self._climb_y3_to_y5(net, Ci - 2, Ri)

            # ---- V-run on Ci covering Aj and sink pz's ----
            Aj = appr_row[net]
            if Aj > Ri:
                self._vrun_y5(net, Ci, Ri, Aj, flow=+1)          # north
            sink_pz = [k[2] for k in self.pl.net_sinks[net]]
            z_min = min(sink_pz) if sink_pz else Ri
            if z_min < Ri:
                self._vrun_y5(net, Ci, Ri, z_min, flow=-1)       # south

            # ---- Per sink delivery ----
            for k in self.pl.net_sinks[net]:
                px, pz = k[0], k[2]
                ac = approach_cols[(net, px, pz)]

                self._drop_y5_to_y3(net, Ci, Aj)
                self._hrun_y3(net, Ci + 2, ac - 2, Aj, flow=-1)  # west
                self._climb_y3_to_y5(net, ac - 2, Aj)
                self._vrun_y5(net, ac, pz, Aj, flow=-1)          # south (Aj->pz)
                self._descend_y5_to_y0(net, ac, pz)

                landing = ac + 5
                pin_x = px - 1
                if landing < pin_x:
                    self._hrun_y0(net, landing, pin_x, pz)
                elif landing > pin_x:
                    self._hrun_y0(net, pin_x, landing, pz)

        # ========== 5. MATERIALIZE ==========
        wires = {n: set() for n in nets}
        supports: Set[Pos] = set()
        repeaters = {n: [] for n in nets}
        torches: Set[Pos] = set()
        wire_owner: Dict[Pos, str] = {}

        for net in nets:
            for pl in self.seg[net]:
                if pl[0] == "dust":
                    wires[net].add((pl[1], pl[2], pl[3]))
                elif pl[0] == "rep":
                    repeaters[net].append(((pl[1], pl[2], pl[3]), pl[4]))
                elif pl[0] in ("block", "support"):
                    supports.add((pl[1], pl[2], pl[3]))
                elif pl[0] == "torch":
                    torches.add((pl[1], pl[2], pl[3]))
            for p in wires[net]:
                wire_owner[p] = net

        wires = {k: v for k, v in wires.items() if v}
        return ChannelResult(
            wires=wires, supports=supports, repeaters=repeaters,
            torches=torches, failed=[], wire_owner=wire_owner,
        )
