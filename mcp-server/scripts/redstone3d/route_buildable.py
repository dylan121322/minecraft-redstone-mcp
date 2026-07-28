"""
route_buildable.py — 2-LAYER directional router producing PHYSICALLY BUILDABLE
redstone. Replaces the free-form 3D maze whose "shared==0 legal" ignored
adjacency shorts + floating dust (see memory riscv-redstone-router-bug).

Unified representation: routing produces PLACEMENTS — typed voxels:
    ("dust",   x,y,z)          redstone_wire
    ("rep",    x,y,z, facing)  repeater (facing = REVERSE of signal flow)
    ("block",  x,y,z)          solid (carries strong power up a via)
    ("support",x,y,z)          solid (holds a raised wire; no signal)
materialize() collects dust->wires, rep->repeaters, block/support->supports.

Physics honored (all verified in-game on vanilla /setblock, see
redstone-setblock-physics):
  * y=0 signal plane; two different nets' dust may never be adjacent
    (orthogonal OR diagonal, same plane) -> hard reject.
  * crossings go OVER via the verified bridge gadget:
      climb:  dust(y0) -> rep -> block(y0)+dust(y1) -> block(y1)+dust(y2)
      run:    dust(y2) with a support block at y1 under each
      descend:dust(y2) -> block(y0,top y1)+dust(y1) -> dust(y0)
  * repeater every <=14 dust steps; facing = reverse(flow).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
from collections import deque
from placer import Placement

Pos = Tuple[int, int, int]
XZ = Tuple[int, int]

_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
_PLANE_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
MAX_RUN = 14
FLOW_FACING = {(1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south"}


@dataclass
class BuildResult:
    wires: Dict[str, Set[Pos]]
    supports: Set[Pos]
    repeaters: Dict[str, List[Tuple[Pos, str]]]
    bridges: Dict[str, int]
    failed: List[str]
    wire_owner: Dict[Pos, str] = field(default_factory=dict)
    torches: List[Pos] = field(default_factory=list)

    def total_wires(self) -> int:
        return sum(len(w) for w in self.wires.values())


class BuildableRouter:
    def __init__(self, placement: Placement, margin=10):
        self.pl = placement
        self.margin = margin
        self.cell_xz: Set[XZ] = set((p[0], p[2]) for p in placement.occupancy)
        self.pin_net: Dict[XZ, str] = {}
        for net, pos in placement.net_sources.items():
            self.pin_net[(pos[0], pos[2])] = net
        for net, sinks in placement.net_sinks.items():
            for pos in sinks:
                self.pin_net[(pos[0], pos[2])] = net
        mn, mx = placement.bounds
        self.bx = (mn[0]-margin, mx[0]+margin)
        self.bz = (mn[2]-margin, mx[2]+margin)
        self.base_y = mn[1]
        self.owner0: Dict[XZ, str] = {}    # y=0 wire owner
        self.owner2: Dict[XZ, str] = {}    # y=2 bridge wire owner
        self.support1: Dict[XZ, str] = {}  # y=1 support/block owner

    # ---------- helpers ----------
    def _foreign_plane(self, xz: XZ, net: str, owner: Dict[XZ, str]) -> bool:
        for dx, dz in _PLANE_SHELL:
            o = owner.get((xz[0]+dx, xz[1]+dz))
            if o is not None and o != net:
                return True
        return False

    def _foreign_pin_adj(self, xz: XZ, net: str, goal: XZ) -> bool:
        """True if xz sits in the 8-neighbourhood of a FOREIGN pin. Pins are
        fixed at y0 before routing, so a wire that grazes another net's pin
        shorts it (the source of the 38 y0 shorts: nets threading past adjacent
        gate-input pins). Reject such cells during BFS. The goal's OWN pin ring
        is exempt (the wire must reach into its own sink)."""
        for dx, dz in _PLANE_SHELL:
            q = (xz[0]+dx, xz[1]+dz)
            if q == goal:
                continue
            o = self.pin_net.get(q)
            if o is not None and o != net:
                return True
        return False

    def _in_box(self, xz: XZ) -> bool:
        return self.bx[0] <= xz[0] <= self.bx[1] and self.bz[0] <= xz[1] <= self.bz[1]

    # ---------- y=0 planar BFS ----------
    def _plane_bfs(self, tree: Set[XZ], goal: XZ, net: str) -> Optional[List[XZ]]:
        prev = {}; seen = set(tree); q = deque(tree)
        while q:
            cur = q.popleft()
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen:
                    continue
                if nx != goal:
                    if not self._in_box(nx):
                        continue
                    if nx in self.cell_xz:
                        continue
                    o = self.owner0.get(nx)
                    if o is not None and o != net:
                        continue
                    if nx in self.pin_net:          # never transit through a pin
                        continue
                    if self._foreign_plane(nx, net, self.owner0):
                        continue
                    if self._foreign_pin_adj(nx, net, goal):
                        continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    # ---------- top-level ----------
    def route(self, verbose: bool = False) -> BuildResult:
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]

        def span(n):
            s = self.pl.net_sources[n]; ks = self.pl.net_sinks[n]
            return max(abs(s[0]-k[0])+abs(s[2]-k[2]) for k in ks)
        nets.sort(key=lambda n: (len(self.pl.net_sinks[n]), span(n)))

        placements: Dict[str, List[tuple]] = {n: [] for n in nets}
        need_bridge: List[Tuple[str, XZ]] = []

        y0 = self.base_y
        for net in nets:
            s = self.pl.net_sources[net]
            src_xz = (s[0], s[2])
            self.owner0.setdefault(src_xz, net)
            tree: Set[XZ] = {src_xz}
            first = True
            for k in sorted(self.pl.net_sinks[net], key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2])):
                goal = (k[0], k[2])
                path = self._plane_bfs(tree, goal, net)
                if path is None:
                    need_bridge.append((net, goal))
                    continue
                for (x, z) in path:
                    self.owner0[(x, z)] = net
                    if (x, z) not in self.pin_net:
                        tree.add((x, z))
                        placements[net].append(("dust", x, y0, z))
                if first:
                    tree.discard(src_xz)
                    first = False

        flat_ok = len(nets) - len({n for n, _ in need_bridge})
        if verbose:
            print(f"  y=0 routed: {flat_ok}/{len(nets)} flat, "
                  f"{len(need_bridge)} sink(s) need bridge", flush=True)

        bridges: Dict[str, int] = {n: 0 for n in nets}
        climbed: Dict[str, Set[XZ]] = {}
        # route bridges sink-by-sink; sort so a net's sinks are consecutive
        for net, goal in sorted(need_bridge, key=lambda ng: ng[0]):
            gadget = self._bridge(net, goal, placements, climbed)
            if gadget:
                placements[net].extend(gadget)
                bridges[net] += 1

        return self._materialize(nets, placements, bridges)

    def _net_wire_xzs(self, net, placements) -> Set[XZ]:
        """xz of this net's y=0 dust so far (bridge can start from one)."""
        out = set()
        for pl in placements[net]:
            if pl[0] == "dust" and pl[2] == self.base_y:
                out.add((pl[1], pl[3]))
        s = self.pl.net_sources[net]
        out.add((s[0], s[2]))
        return out

    def _y2_free(self, xz, net):
        """Can net's y=2 bridge dust occupy xz? Reject if a FOREIGN y=2 wire is
        in the 8-neighborhood (Agent B: parallel y=2 need sep>=2, and diagonal
        y=2 also couples) or a foreign y=1 support is here. Crossings over y=0
        are FREE (Agent B), so we ignore owner0 entirely on the y=2 plane."""
        if not self._in_box(xz):
            return False
        o = self.owner2.get(xz)
        if o is not None and o != net:
            return False
        so = self.support1.get(xz)
        if so is not None and so != net:
            return False
        for dx, dz in _PLANE_SHELL:
            o = self.owner2.get((xz[0]+dx, xz[1]+dz))
            if o is not None and o != net:
                return False
        return True

    def _y2_bfs(self, sources, goal, net):
        prev = {}; seen = set(sources); q = deque(sources)
        while q:
            cur = q.popleft()
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen:
                    continue
                if nx != goal and not self._y2_free(nx, net):
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    def _bridge(self, net, goal_xz, placements, climbed):
        """Route a bridged sink on the CROSS plane (y=4). Climb ONCE per net via
        a 1x1 vertical torch tower (2 torches y0->y4, NON-inverting, verified in
        test_bridge_gadget.py) at its source; subsequent sinks branch off the
        net's existing y=4 tree. Descend into each goal pin with a short +x
        staircase (y4->y0, 4 cells — one obstacle's worth, not a deep trunk).

        The 1x1 tower footprint (vs the old 3-wide lateral climb) is what removes
        the y0-adjacency shorts; the higher cross plane (y4 vs y2) keeps bridge
        wires clear of the y0 signal plane. `climbed` maps net -> set of y=4 xz
        it occupies. Returns typed placements or None."""
        y0 = self.base_y; y4 = y0 + 4
        gx, gz = goal_xz
        p = []

        if net not in climbed:
            s = self.pl.net_sources[net]
            sx, sz = s[0], s[2]
            # 1x1 torch tower at (sx+1, sz): repeater feed reads the source dust
            # to its west, block0, 2 standing torches (each +2 Y, 2 inversions =
            # non-inverting), top dust at y4+1 (odd cross plane, like the trunk).
            tx = sx + 1
            p.append(("rep", tx, y0, sz, "west"))     # repeater faces west (reads sx)
            self.owner0[(tx, sz)] = net
            yy = y0
            for _ in range(2):
                p.append(("block", tx, yy, sz))       # block
                p.append(("torch", tx, yy+1, sz))     # standing torch
                yy += 2
            # top dust on the final block, at y4+1
            p.append(("dust", tx, y4+1, sz))
            self.owner2[(tx, sz)] = net; self.support1[(tx, sz)] = net
            climbed[net] = {(tx, sz)}

        # cross-plane BFS (y=4+1 dust) from the net's tree to the descent top at
        # (gx-4, gz): a 4-cell +x staircase then lands y0 at gx-1 (pin west feed),
        # never covering the pin at gx.
        y4_top = (gx - 5, gz)
        path = self._y2_bfs(set(climbed[net]), y4_top, net)
        if path is None:
            return None
        for (x, z) in path:
            if (x, z) in climbed[net]:
                continue
            p.append(("support", x, y4, z)); p.append(("dust", x, y4+1, z))
            self.owner2[(x, z)] = net; self.support1[(x, z)] = net
            climbed[net].add((x, z))
        # DESCEND: +x staircase from (gx-5, y4+1) down to y0 at (gx-1), then the
        # goal dust at gx-1 feeds the west-facing input repeater at gx.
        cx, cy = gx - 5, y4 + 1
        while cy > y0:
            cx += 1
            cy -= 1
            if cy > y0:
                p.append(("block", cx, cy-1, gz)); p.append(("dust", cx, cy, gz))
            else:
                p.append(("dust", cx, y0, gz))
            self.owner0[(cx, gz)] = net
        return p

    def _materialize(self, nets, placements, bridges):
        res = BuildResult({}, set(), {}, dict(bridges), [], {}, [])
        for net in nets:
            res.wires[net] = set()
            res.repeaters[net] = []
            for pl in placements[net]:
                role = pl[0]
                if role == "dust":
                    res.wires[net].add((pl[1], pl[2], pl[3]))
                elif role == "rep":
                    res.repeaters[net].append(((pl[1], pl[2], pl[3]), pl[4]))
                elif role in ("block", "support"):
                    res.supports.add((pl[1], pl[2], pl[3]))
                elif role == "torch":
                    res.torches.append((pl[1], pl[2], pl[3]))
            # repeater insertion on long flat dust runs (source-ordered)
            self._insert_repeaters(net, placements[net], res)
            for p in res.wires[net]:
                res.wire_owner[p] = net
            for (pos, _f) in res.repeaters[net]:
                res.wire_owner[pos] = net
        res.failed = [n for n in nets if not placements[n]]
        return res

    def _insert_repeaters(self, net, pls, res):
        """Walk the y=0 dust in placement order; every MAX_RUN steps replace a
        dust with a repeater facing the flow. Bridges already have their own
        repeater and are short, so only refresh base-plane runs."""
        dust0 = [(pl[1], pl[2], pl[3]) for pl in pls if pl[0] == "dust" and pl[2] == self.base_y]
        run = 0
        for i, p in enumerate(dust0):
            run += 1
            if run >= MAX_RUN and i+1 < len(dust0):
                nxt = dust0[i+1]
                d = (nxt[0]-p[0], nxt[2]-p[2])
                if nxt[1] == p[1] and abs(d[0])+abs(d[1]) == 1:  # adjacent horizontal
                    f = FLOW_FACING.get(d)
                    if f and p in res.wires[net]:
                        res.repeaters[net].append((p, f))
                        res.wires[net].discard(p)
                        run = 0
