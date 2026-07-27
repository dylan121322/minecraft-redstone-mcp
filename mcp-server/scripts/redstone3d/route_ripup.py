"""
route_ripup.py — RIP-UP & REROUTE router (PathFinder-style negotiated congestion)
with TRUE redstone adjacency legality. Goal: MINIMAL wiring AND 0 shorts — the
combination that no single-pass scheme achieves (see ROUTER_JOURNAL.md §IV/V).

Why this converges where one-pass schemes don't: nets are NOT hard-forbidden from
contested cells during routing (that causes sequential-blindness — an early net
can't see a later one). Instead every net routes by SHORTEST cost-aware path,
where a cell's cost rises with how congested it is. After each iteration we find
real adjacency shorts, raise the *history* cost on those cells, rip up everything,
and reroute. Over iterations nets with cheaper alternatives vacate contested
cells until no two different nets' dust are adjacent.

Legality = TRUE redstone adjacency (ROUTER_JOURNAL §I): two different nets' y=0
dust short if 8-neighbour adjacent (orthogonal OR diagonal) on the same plane.
Floating dust and vertical shorts are avoided by keeping signal routing on y=0
(the plane) and only using a verified torch-tower bridge to hop a hard blockage.

Placements (same typed tuples as route_buildable):
    ("dust",x,y,z) ("rep",x,y,z,facing) ("block",x,y,z) ("support",x,y,z)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
import heapq
from placer import Placement

Pos = Tuple[int, int, int]
XZ = Tuple[int, int]

_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
MAX_RUN = 13
FLOW_FACING = {(1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south"}


@dataclass
class RipupResult:
    wires: Dict[str, Set[Pos]]
    supports: Set[Pos]
    repeaters: Dict[str, List[Tuple[Pos, str]]]
    failed: List[str]
    wire_owner: Dict[Pos, str] = field(default_factory=dict)
    iterations: int = 0

    def total_wires(self) -> int:
        return sum(len(w) for w in self.wires.values())


class RipupRouter:
    def __init__(self, placement: Placement, margin=8):
        self.pl = placement
        self.cell_xz: Set[XZ] = set((p[0], p[2]) for p in placement.occupancy)
        # pin -> owning net; pins are endpoints, never transit cells
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

    def _in_box(self, xz: XZ) -> bool:
        return self.bx[0] <= xz[0] <= self.bx[1] and self.bz[0] <= xz[1] <= self.bz[1]

    def _shell_congestion(self, xz, net, occ):
        """Foreign-net y0 dust in xz's 8-neighbour shell, counting BOTH this
        pass's occ AND the previous iteration's full map (present cost). Prev-occ
        gives every net visibility of where all nets were last round, breaking
        the correlated-flip oscillation."""
        prev = getattr(self, "_prev_occ", {})
        c = 0
        for dx, dz in _SHELL:
            q = (xz[0]+dx, xz[1]+dz)
            o = occ.get(q)
            if o is not None and o != net:
                c += 1
            else:
                po = prev.get(q)
                if po is not None and po != net:
                    c += 1
        return c

    def _astar(self, sources: Set[XZ], goal: XZ, net: str,
               occ: Dict[XZ, str], hist: Dict[XZ, float]) -> Optional[List[XZ]]:
        """Cost-aware A* on y=0 from any source cell to goal. Cost of entering a
        cell = 1 (length) + SHORT_PEN * foreign-shell-congestion + hist. We do
        NOT hard-forbid foreign cells (that's the sequential-blindness trap);
        congestion+history make nets negotiate apart over iterations. Hard blocks:
        out of box, cell bodies, foreign pins, and transiting ANY pin."""
        SHORT_PEN = 6.0
        def h(p): return abs(p[0]-goal[0]) + abs(p[1]-goal[1])
        best: Dict[XZ, float] = {}
        prev: Dict[XZ, XZ] = {}
        pq = []
        for s in sources:
            best[s] = 0.0
            heapq.heappush(pq, (h(s), 0.0, s))
        while pq:
            f, g, cur = heapq.heappop(pq)
            if g > best.get(cur, 1e18):
                continue
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in best and best[nx] <= g:
                    pass
                if nx != goal:
                    if not self._in_box(nx):
                        continue
                    if nx in self.cell_xz:
                        continue
                    if nx in self.pin_net:      # never transit a pin (endpoint only)
                        continue
                cost = 1.0 + SHORT_PEN * self._shell_congestion(nx, net, occ) + hist.get(nx, 0.0)
                ng = g + cost
                if ng < best.get(nx, 1e18):
                    best[nx] = ng
                    prev[nx] = cur
                    heapq.heappush(pq, (ng + h(nx), ng, nx))
        return None

    def _route_all(self, nets, hist, prev_occ=None):
        """One pass: route every net's fan-out tree on y=0 against current hist
        AND a present-cost field from the PREVIOUS iteration's full occupancy
        (prev_occ). Using last-iter's complete map as present-cost breaks the
        correlated-flip oscillation: every net sees where ALL nets were, not just
        the ones routed earlier this pass. Returns (paths, occ)."""
        paths: Dict[str, List[XZ]] = {}
        occ: Dict[XZ, str] = {}
        # present-cost congestion source: prior full map (if any) overlaid with
        # this pass's growing occ. We pass a merged view into _astar via occ, but
        # seed the shell-congestion lookups with prev_occ too.
        self._prev_occ = prev_occ or {}
        # deterministic order: fewest sinks / shortest first (stable)
        def span(n):
            s = self.pl.net_sources[n]; ks = self.pl.net_sinks[n]
            return max(abs(s[0]-k[0])+abs(s[2]-k[2]) for k in ks)
        order = sorted(nets, key=lambda n: (len(self.pl.net_sinks[n]), span(n)))
        for net in order:
            s = self.pl.net_sources[net]
            src = (s[0], s[2])
            tree: Set[XZ] = {src}
            cells: List[XZ] = []
            first = True
            ok = True
            for k in sorted(self.pl.net_sinks[net],
                            key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2])):
                goal = (k[0], k[2])
                path = self._astar(tree, goal, net, occ, hist)
                if path is None:
                    ok = False
                    continue
                for c in path:
                    if c not in self.pin_net:
                        tree.add(c)
                        if c not in cells:
                            cells.append(c)
                            occ[c] = net
                if first:
                    tree.discard(src)
                    first = False
            paths[net] = cells
        return paths, occ

    def _find_shorts(self, occ):
        """Cells where two different nets' y0 dust are 8-neighbour adjacent.
        Returns a set of the contested cells (both sides)."""
        bad: Set[XZ] = set()
        for xz, net in occ.items():
            for dx, dz in _SHELL:
                o = occ.get((xz[0]+dx, xz[1]+dz))
                if o is not None and o != net:
                    bad.add(xz)
                    bad.add((xz[0]+dx, xz[1]+dz))
        return bad

    def route(self, max_iters=60, verbose=False):
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        hist: Dict[XZ, float] = {}
        HIST_INC = 2.0
        best_paths = None; best_bad = None
        prev_occ = None
        for it in range(max_iters):
            paths, occ = self._route_all(nets, hist, prev_occ)
            prev_occ = occ
            bad = self._find_shorts(occ)
            if best_bad is None or len(bad) < len(best_bad):
                best_bad = set(bad); best_paths = {n: list(p) for n, p in paths.items()}
            if verbose and (it % 5 == 0 or not bad):
                print(f"  iter {it}: shorted cells={len(bad)}", flush=True)
            if not bad:
                best_paths = paths; best_bad = bad
                break
            for c in bad:
                hist[c] = hist.get(c, 0.0) + HIST_INC
        return self._materialize(nets, best_paths, len(best_bad), it + 1)

    def _materialize(self, nets, paths, nbad, iters):
        res = RipupResult({}, set(), {}, [], {}, iters)
        y0 = self.base_y
        for net in nets:
            res.wires[net] = set()
            res.repeaters[net] = []
            cells = paths.get(net, [])
            # rebuild ordered per-sink runs for repeater insertion: cells is a
            # tree in visit order; insert a repeater every MAX_RUN steps along
            # consecutive-adjacent runs, facing the travel direction.
            run = 0
            for i, (x, z) in enumerate(cells):
                placed_rep = False
                if i > 0:
                    px, pz = cells[i-1]
                    d = (x - px, z - pz)
                    if abs(d[0]) + abs(d[1]) == 1:   # adjacent step
                        run += 1
                        if run >= MAX_RUN:
                            f = FLOW_FACING.get(d)
                            if f:
                                res.repeaters[net].append(((x, y0, z), f))
                                placed_rep = True
                                run = 0
                    else:
                        run = 0   # tree jumped (new branch); reset
                if not placed_rep:
                    res.wires[net].add((x, y0, z))
            for p in res.wires[net]:
                res.wire_owner[p] = net
            for (pos, _f) in res.repeaters[net]:
                res.wire_owner[pos] = net
        res.failed = [n for n in nets if not paths.get(n)]
        return res
