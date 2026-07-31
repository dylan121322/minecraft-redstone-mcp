"""
global_first.py — P1+P2 prototype: allocate GLOBAL trunks first, then place the
gate clusters to suit them.

Rationale from measurement: partitioning only rescues local nets (ALU_Control
local 19->23, shorts 7->0), while most failures are GLOBAL nets (ImmGen 27 of 41,
Mux2to1 16 of 34). With the placement fixed, those long connections have to grab
whatever is left, which is why they fail. So decide the trunks first and let the
clusters move to meet them.

This prototype answers, without emitting geometry:
  * how many trunk corridors (and therefore cross layers) a module needs,
  * where each cluster WANTS to sit so its global pins are near their trunks,
  * how much total global wire the reordering saves versus the current placement.
"""
from __future__ import annotations
import sys, os, json
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set

XZ = Tuple[int, int]


@dataclass
class Trunk:
    net: str
    layer: int          # cross layer index (0,2,4.. = E-W; 1,3.. = N-S)
    track: int          # corridor index within the layer
    z: int              # for E-W trunks: the row it runs along
    x_span: Tuple[int, int]
    taps: List[XZ] = field(default_factory=list)   # where towers meet it


@dataclass
class ClusterPlan:
    cid: int
    gates: List[str]
    cur_x: int
    want_x: int         # x that minimises this cluster's global wire
    shift: int


class GlobalFirstPlanner:
    """Plan trunks for global nets, then compute each cluster's preferred x."""

    TRACK_PITCH = 2      # centre-to-centre spacing inside a layer (0 shorts)
    LAYER_PITCH = 4      # Y between cross layers (even torch count for towers)

    def __init__(self, placement, zone_width: int = 64):
        self.pl = placement
        self.W = zone_width
        mn, mx = placement.bounds
        self.x0, self.x1 = mn[0], mx[0]
        self.z0, self.z1 = mn[2], mx[2]
        self.base_y = mn[1]

    # ---------- classification ----------
    def _zone(self, x: int) -> int:
        return (x - self.x0) // self.W

    def classify(self):
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        local, glob = [], []
        for n in nets:
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            (local if len({self._zone(x) for x in xs}) == 1 else glob).append(n)
        return nets, local, glob

    # ---------- P1: trunk allocation ----------
    def allocate_trunks(self, glob: List[str]) -> List[Trunk]:
        """One dedicated corridor per global net. Corridors are packed
        TRACK_PITCH apart on a layer; a layer holds as many as the z range allows,
        then a new layer opens. Same layer + same direction + pitch 2 => no two
        trunks can ever be adjacent, so shorts are structurally impossible."""
        z_room = max(1, (self.z1 - self.z0) // self.TRACK_PITCH)
        trunks = []
        # long nets first: they benefit most from a clean corridor
        def span(n):
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            return max(xs) - min(xs)
        for i, n in enumerate(sorted(glob, key=span, reverse=True)):
            layer = (i // z_room) * 2          # even layers: E-W trunks
            track = i % z_room
            z = self.z0 + track * self.TRACK_PITCH
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            taps = [(self.pl.net_sources[n][0], self.pl.net_sources[n][2])] + \
                   [(k[0], k[2]) for k in self.pl.net_sinks[n]]
            trunks.append(Trunk(n, layer, track, z, (min(xs), max(xs)), taps))
        return trunks

    # ---------- P2: cluster placement preference ----------
    def cluster_wants(self, trunks: List[Trunk]) -> List[ClusterPlan]:
        """Group gates into clusters by their current column, then compute the x
        each cluster would prefer: the mean x of the trunk taps its gates own.
        A cluster whose global pins all tap trunks far east wants to move east."""
        cols: Dict[int, List[str]] = {}
        for name, pc in self.pl.placed.items():
            cols.setdefault(pc.origin[0], []).append(name)
        tap_x: Dict[str, List[int]] = {}
        for t in trunks:
            for (tx, tz) in t.taps:
                tap_x.setdefault((tx, tz), []).append(t.x_span)
        out = []
        for cid, (cx, gates) in enumerate(sorted(cols.items())):
            pins: List[int] = []
            for g in gates:
                pc = self.pl.placed[g]
                for p in list(pc.input_pins.values()) + list(pc.output_pins.values()):
                    key = (p[0], p[2])
                    for span in tap_x.get(key, []):
                        pins.append((span[0] + span[1]) // 2)
            want = int(sum(pins) / len(pins)) if pins else cx
            out.append(ClusterPlan(cid, gates, cx, want, want - cx))
        return out

    # ---------- reporting ----------
    def report(self):
        nets, local, glob = self.classify()
        trunks = self.allocate_trunks(glob)
        clusters = self.cluster_wants(trunks)
        layers = 1 + max((t.layer for t in trunks), default=0)
        z_room = max(1, (self.z1 - self.z0) // self.TRACK_PITCH)
        trunk_len = sum(t.x_span[1] - t.x_span[0] for t in trunks)
        cur_global = 0
        for n in glob:
            s = self.pl.net_sources[n]
            for k in self.pl.net_sinks[n]:
                cur_global += abs(s[0] - k[0]) + abs(s[2] - k[2])
        shifts = [abs(c.shift) for c in clusters]
        return {
            "nets": len(nets), "local": len(local), "global": len(glob),
            "z_room_per_layer": z_room,
            "cross_layers_needed": layers,
            "trunk_total_len": trunk_len,
            "current_global_wire": cur_global,
            "trunk_vs_current": round(trunk_len / cur_global, 2) if cur_global else 0,
            "clusters": len(clusters),
            "mean_abs_shift": int(sum(shifts) / len(shifts)) if shifts else 0,
            "max_abs_shift": max(shifts) if shifts else 0,
        }


def main():
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or ["alu1"]
    W = next((int(a) for a in sys.argv[1:] if a.isdigit()), 64)
    for mod in mods:
        pl = place(nls[mod], col_gap=16, row_gap=16)
        r = GlobalFirstPlanner(pl, zone_width=W).report()
        print(f"[{mod} W={W}] nets={r['nets']} local={r['local']} global={r['global']}")
        print(f"    trunks: {r['global']} corridors, {r['cross_layers_needed']} cross "
              f"layer(s), {r['z_room_per_layer']} tracks/layer")
        print(f"    trunk length {r['trunk_total_len']} vs current global wire "
              f"{r['current_global_wire']}  (x{r['trunk_vs_current']})")
        print(f"    clusters={r['clusters']} mean|shift|={r['mean_abs_shift']} "
              f"max|shift|={r['max_abs_shift']}")


if __name__ == "__main__":
    main()
