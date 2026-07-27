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
        """Route a bridged sink on the y=2 plane. Climb ONCE per net (the first
        bridge for that net) at its source; subsequent sinks branch off the
        net's existing y=2 tree. Descend into each goal pin.

        `climbed` maps net -> the y=2 xz where its climb tops out (tree root).
        Returns typed placements or None."""
        y0 = self.base_y; y1 = y0+1; y2 = y0+2
        gx, gz = goal_xz
        p = []

        if net not in climbed:
            # climb near the source. Source is an output pin at west; put the
            # Agent-A climb just east of it.
            s = self.pl.net_sources[net]
            sx, sz = s[0], s[2]
            # climb footprint: rep@sx+1, block+dust@sx+2, block+dust->y2@sx+3
            p.append(("rep", sx+1, y0, sz, "west"))
            self.owner0[(sx+1, sz)] = net
            p.append(("block", sx+2, y0, sz)); p.append(("dust", sx+2, y1, sz))
            self.owner0[(sx+2, sz)] = net; self.support1[(sx+2, sz)] = net
            p.append(("block", sx+3, y1, sz)); p.append(("dust", sx+3, y2, sz))
            self.support1[(sx+3, sz)] = net; self.owner2[(sx+3, sz)] = net
            climbed[net] = {(sx+3, sz)}

        # y=2 BFS from the net's existing y=2 tree to the DESCENT TOP, which is
        # the y=2 cell at (gx-2, gz). Agent A descent chain then is:
        #   y2 dust @ (gx-2,gz)  ->  block@y0(top y1)+dust@y1 @ (gx-1,gz)  ->  y0 dust @ (gx,gz)=goal
        y2_top = (gx-2, gz)
        path = self._y2_bfs(set(climbed[net]), y2_top, net)
        if path is None:
            return None
        for (x, z) in path:
            if (x, z) in climbed[net]:
                continue
            p.append(("support", x, y1, z)); p.append(("dust", x, y2, z))
            self.owner2[(x, z)] = net; self.support1[(x, z)] = net
            climbed[net].add((x, z))
        # DESCEND (Agent A exact geometry)
        p.append(("block", gx-1, y0, gz)); p.append(("dust", gx-1, y1, gz))
        self.owner0[(gx-1, gz)] = net; self.support1[(gx-1, gz)] = net
        p.append(("dust", gx, y0, gz))
        self.owner0[(gx, gz)] = net
        return p

    def _materialize(self, nets, placements, bridges):
        res = BuildResult({}, set(), {}, dict(bridges), [], {})
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
