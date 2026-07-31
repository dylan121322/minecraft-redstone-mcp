"""
partition.py — P0 of PARTITION_PLAN: plan before routing.

Global routing collapses with scale (measured: 25 gates 0 shorts, 92 gates 25,
197 gates 159). This module produces a PLAN instead of geometry:

  * split the field into x-zones,
  * classify every net local (one zone) or global (crosses zones),
  * pre-select each sink's delivery method (planar / staircase / tower) from the
    room actually available around its feed cell,
  * build a reservation ledger for the vertical resources those deliveries need,
    so conflicts surface here rather than as a mid-route failure.

Nothing here is module-specific; it reads only a Placement.
"""
from __future__ import annotations
import sys, os, json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set

Pos = Tuple[int, int, int]
XZ = Tuple[int, int]
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
_SHELL = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dz) != (0, 0)]


@dataclass
class SinkPlan:
    net: str
    pin: XZ                     # the gate input pin
    feed: XZ                    # the only cell that can drive it (pin west)
    zone: int
    method: str                 # "planar" | "stair" | "tower"
    reserve: Set[XZ] = field(default_factory=set)   # cells this delivery needs


@dataclass
class Plan:
    zone_width: int
    zones: int
    local_nets: List[str]
    global_nets: List[str]
    net_zones: Dict[str, Set[int]]
    sinks: List[SinkPlan]
    contested: List[Tuple[XZ, List[str]]]           # feed/reserve clashes
    stats: dict


class Planner:
    def __init__(self, placement, zone_width: int = 64):
        self.pl = placement
        self.W = zone_width
        mn, mx = placement.bounds
        self.x0, self.x1 = mn[0], mx[0]
        self.base_y = mn[1]
        self.cell_xz: Set[XZ] = {(p[0], p[2]) for p in placement.occupancy}
        self.pin_xz: Dict[XZ, str] = {}
        for n, p in placement.net_sources.items():
            self.pin_xz[(p[0], p[2])] = n
        for n, ks in placement.net_sinks.items():
            for p in ks:
                self.pin_xz[(p[0], p[2])] = n

    # ---------- zoning ----------
    def zone_of_x(self, x: int) -> int:
        return (x - self.x0) // self.W

    def net_zones(self, net: str) -> Set[int]:
        xs = [self.pl.net_sources[net][0]] + [k[0] for k in self.pl.net_sinks[net]]
        return {self.zone_of_x(x) for x in xs}

    # ---------- room probes ----------
    def _free(self, c: XZ) -> bool:
        return c not in self.cell_xz and c not in self.pin_xz

    def west_run(self, feed: XZ, limit: int = 40) -> int:
        """How many consecutive free cells run west from the feed cell. A planar
        approach or a staircase both need a clear west run."""
        n = 0
        x = feed[0]
        while n < limit and self._free((x, feed[1])):
            n += 1
            x -= 1
        return n

    def tower_fits(self, feed: XZ) -> bool:
        """A 2x2 down tower needs the feed column plus three neighbours free in
        at least one of the verified rotations."""
        for arm, side in (((1, 0), (0, 1)), ((1, 0), (0, -1)),
                          ((0, 1), (1, 0)), ((0, -1), (1, 0))):
            cells = [feed,
                     (feed[0] + arm[0], feed[1] + arm[1]),
                     (feed[0] + side[0], feed[1] + side[1]),
                     (feed[0] + arm[0] + side[0], feed[1] + arm[1] + side[1])]
            if all(self._free(c) for c in cells):
                return True
        return False

    # ---------- planning ----------
    def plan(self) -> Plan:
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        nz = {n: self.net_zones(n) for n in nets}
        local = [n for n in nets if len(nz[n]) == 1]
        glob = [n for n in nets if len(nz[n]) > 1]

        sinks: List[SinkPlan] = []
        claims: Dict[XZ, List[str]] = {}
        for n in nets:
            for k in self.pl.net_sinks[n]:
                pin = (k[0], k[2])
                feed = (pin[0] - 1, pin[1])
                z = self.zone_of_x(pin[0])
                run = self.west_run(feed)
                if not self._free(feed):
                    method = "blocked"
                    reserve = {feed}
                elif run >= 8:
                    method = "planar"
                    reserve = {feed}
                elif self.tower_fits(feed):
                    method = "tower"
                    reserve = {feed,
                               (feed[0] + 1, feed[1]),
                               (feed[0], feed[1] + 1),
                               (feed[0] + 1, feed[1] + 1)}
                elif run >= 3:
                    method = "stair"
                    reserve = {(feed[0] - i, feed[1]) for i in range(run)}
                else:
                    method = "blocked"
                    reserve = {feed}
                sp = SinkPlan(n, pin, feed, z, method, reserve)
                sinks.append(sp)
                for c in reserve:
                    claims.setdefault(c, []).append(n)

        contested = [(c, owners) for c, owners in claims.items()
                     if len({o for o in owners}) > 1]

        from collections import Counter
        by_zone = Counter(s.zone for s in sinks)
        by_method = Counter(s.method for s in sinks)
        stats = {
            "nets": len(nets), "local": len(local), "global": len(glob),
            "sinks": len(sinks),
            "sinks_per_zone": dict(sorted(by_zone.items())),
            "methods": dict(by_method),
            "contested_cells": len(contested),
            "zone_width": self.W,
            "zones": self.zone_of_x(self.x1) + 1,
        }
        return Plan(self.W, stats["zones"], local, glob, nz, sinks,
                    contested, stats)


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or ["alu1"]
    widths = [int(a) for a in sys.argv[1:] if a.isdigit()] or [64]
    for mod in mods:
        nl = nls[mod]
        for W in widths:
            pl = place(nl, col_gap=16, row_gap=16)
            p = Planner(pl, zone_width=W).plan()
            s = p.stats
            print(f"[{mod} W={W}] zones={s['zones']} nets={s['nets']} "
                  f"local={s['local']} global={s['global']} "
                  f"methods={s['methods']} contested={s['contested_cells']}")
            print(f"    sinks/zone: {s['sinks_per_zone']}")


if __name__ == "__main__":
    main()
