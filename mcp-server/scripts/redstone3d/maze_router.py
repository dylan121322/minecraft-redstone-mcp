"""
maze_router.py — Lee maze routing for redstone nets (after PERSHING/dewey).

Replaces the unbounded A* with a bounded BFS wavefront on a usage matrix:
  - A 3D grid tracks occupancy: each voxel is FREE, a CELL body, or owned by
    a net's wire. Lee's algorithm floods from source cells outward, so search
    is strictly bounded by the routing box (no infinite exploration).
  - Different nets are kept apart by a keep-out: a candidate wire voxel is
    rejected if any orthogonal neighbor holds a DIFFERENT net's wire.
  - Fan-out (multi-sink) uses the classic Lee trick: after routing the first
    sink, ALL wires of that net become sources (distance 0) for the next sink,
    growing a Steiner-like tree.
  - Signal decay: after MAX_RUN consecutive wire steps, drop a repeater facing
    the flow direction to refresh strength to 15.
  - Vertical layering: nets may hop to y=1,2,... to cross congested regions;
    vertical moves cost more so the router prefers the base plane.

This module operates purely on a Placement (from placer.py) and returns a
RouteResult compatible with synth.py.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
from collections import deque
from placer import Placement

Pos = Tuple[int, int, int]
MAX_RUN = 15


@dataclass
class RouteResult:
    wires: Dict[str, Set[Pos]]
    repeaters: Dict[str, List[Tuple[Pos, str]]]
    failed: List[str]
    wire_owner: Dict[Pos, str]

    def total_wires(self) -> int:
        return sum(len(w) for w in self.wires.values())


_HORIZ = [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)]
_VERT = [(0, 1, 0), (0, -1, 0)]


class MazeRouter:
    def __init__(self, placement: Placement, y_min=0, y_max=6, margin=6):
        self.pl = placement
        self.y_min, self.y_max = y_min, y_max
        self.wire_owner: Dict[Pos, str] = {}
        # pins are endpoints (usable) but not through-conductors for other nets
        self.pin_pos: Set[Pos] = set()
        for pc in placement.placed.values():
            self.pin_pos.update(pc.input_pins.values())
            self.pin_pos.update(pc.output_pins.values())
        self.pin_pos.update(placement.primary_inputs.values())
        mn, mx = placement.bounds
        self.bx = (mn[0]-margin, mx[0]+margin)
        self.bz = (mn[2]-margin, mx[2]+margin)

    def _in_box(self, p: Pos) -> bool:
        return (self.bx[0] <= p[0] <= self.bx[1]
                and self.y_min <= p[1] <= self.y_max
                and self.bz[0] <= p[2] <= self.bz[1])

    def _passable(self, p: Pos, net: str) -> bool:
        """Can net's wire occupy p? (endpoints handled by caller)"""
        if not self._in_box(p):
            return False
        if p in self.pl.occupancy and p not in self.pin_pos:
            return False
        owner = self.wire_owner.get(p)
        if owner is not None and owner != net:
            return False
        return True

    def _foreign_adjacent(self, p: Pos, net: str, targets: Set[Pos]) -> bool:
        """Would a wire at p short to a different net? In Minecraft redstone,
        wires conduct to SAME-Y horizontal neighbors and to diagonal-up/down
        neighbors. Two different nets short only if:
          - same-Y orthogonally adjacent, OR
          - vertically adjacent (redstone climbs 1 block on solid support).
        Different Y AND horizontally offset by >=1 do NOT short (no diagonal
        conduction across a gap). We allow those crossings so congested nets
        can weave through separate layers."""
        px, py, pz = p
        # same-Y horizontal neighbors (real short risk)
        for dx, dy, dz in _HORIZ:
            q = (px+dx, py, pz+dz)
            if q in targets:
                continue
            o = self.wire_owner.get(q)
            if o is not None and o != net:
                return True
        # directly above/below (vertical adjacency conducts)
        for dy in (1, -1):
            q = (px, py+dy, pz)
            if q in targets:
                continue
            o = self.wire_owner.get(q)
            if o is not None and o != net:
                return True
        # DIAGONAL RAMP: redstone dust connects to dust one block horizontally
        # AND one block up/down (climbing a step). Two nets whose wires sit at
        # such a diagonal SHORT in-game even though they're not orthogonally
        # adjacent. This was the bug that produced a pathological connected
        # graph (redpiler hang). Reject those placements too.
        for dx, _, dz in _HORIZ:
            for dy in (1, -1):
                q = (px+dx, py+dy, pz+dz)
                if q in targets:
                    continue
                o = self.wire_owner.get(q)
                if o is not None and o != net:
                    return True
        return False

    def _bfs(self, sources: Set[Pos], goal: Pos, net: str) -> Optional[List[Pos]]:
        """Cost-aware wavefront (Dijkstra) from all sources to goal.

        Cost per step = 1 (horizontal) or 3 (vertical layer change) plus the
        voxel's accumulated `history` penalty from rip-up rounds. This makes
        the router negotiate around chronically congested cells rather than
        re-colliding every iteration."""
        import heapq
        hist = getattr(self, "history", {})
        prev: Dict[Pos, Pos] = {}
        best: Dict[Pos, int] = {}
        pq = []
        for s in sources:
            best[s] = 0
            heapq.heappush(pq, (0, s))
        targets = set(sources) | {goal}
        while pq:
            g, cur = heapq.heappop(pq)
            if g > best.get(cur, 1 << 60):
                continue
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for d in _HORIZ + _VERT:
                nx = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
                # Vertical layer changes cost more (need a support column) but
                # a moderate penalty lets a net take a short vertical detour
                # instead of a long planar loop. Long detours pack many wires
                # into one region, which blows up the redpiler adjacency graph
                # (see BUG_nucleation_edges.md). Balance: climb ~6 blocks worth.
                step = 1 if d[1] == 0 else 6
                if nx != goal:
                    if not self._passable(nx, net):
                        continue
                    if self._foreign_adjacent(nx, net, targets):
                        continue
                ng = g + step + hist.get(nx, 0)
                if ng < best.get(nx, 1 << 60):
                    best[nx] = ng
                    prev[nx] = cur
                    heapq.heappush(pq, (ng, nx))
        return None

    def _lay(self, path: List[Pos], net: str, result: RouteResult):
        wires = result.wires.setdefault(net, set())
        run = 0
        for i, p in enumerate(path):
            if p in self.pin_pos:
                self.wire_owner.setdefault(p, net)
                run = 0
                continue
            wires.add(p)
            self.wire_owner[p] = net
            run += 1
            if run >= MAX_RUN and i + 1 < len(path):
                nxt = path[i+1]
                dx, dy, dz = nxt[0]-p[0], nxt[1]-p[1], nxt[2]-p[2]
                facing = {(1,0,0):"west", (-1,0,0):"east",
                          (0,0,1):"north", (0,0,-1):"south"}.get((dx,dy,dz), "west")
                result.repeaters.setdefault(net, []).append((p, facing))
                run = 0

    def _route_one(self, net: str, result: RouteResult) -> bool:
        """Route a single net's full fan-out tree. Returns True if all sinks
        reached. Mutates wire_owner/result for this net only."""
        src = self.pl.net_sources.get(net)
        sinks = self.pl.net_sinks.get(net, [])
        if src is None or not sinks:
            return True
        self.wire_owner.setdefault(src, net)
        tree: Set[Pos] = {src}
        ok = True
        for sink in sorted(sinks, key=lambda s: abs(src[0]-s[0])+abs(src[2]-s[2])):
            path = self._bfs(tree, sink, net)
            if path is None:
                ok = False
                continue
            self._lay(path, net, result)
            for p in path:
                if p not in self.pin_pos:
                    tree.add(p)
        return ok

    def _rip(self, net: str, result: RouteResult):
        """Remove all of net's wires/repeaters, freeing the voxels."""
        for p in list(result.wires.get(net, ())):
            if self.wire_owner.get(p) == net:
                del self.wire_owner[p]
        result.wires.pop(net, None)
        result.repeaters.pop(net, None)

    def route_fast(self) -> RouteResult:
        """Single-pass greedy routing — no rip-up. Fast for small modules (<50 gates).
        Uses relaxed ordering: route easy nets first, skip keep-out to avoid deadlocks."""
        result = RouteResult({}, {}, [], self.wire_owner)
        nets = sorted(self.pl.net_sinks.keys(),
                      key=lambda n: len(self.pl.net_sinks.get(n, [])),
                      reverse=True)
        for net in nets:
            if not self._route_one(net, result):
                result.failed.append(net)
        return result

    def route(self, max_iters: int = 60) -> RouteResult:
        """Rip-up & reroute with negotiated congestion (PathFinder-style).

        Compute-heavy but reliable. Each iteration:
          1. Rip up EVERY net and route all fresh, in hardness order.
          2. A persistent `history` penalty on congested voxels grows each
             round, so nets that lost a contested cell steer around it next
             time instead of oscillating.
        Iterates until all nets route with zero conflicts, or max_iters.

        Order is re-randomized-by-hardness each round; the history term is what
        actually breaks ties and resolves congestion, per Nair/PathFinder.
        """
        self.history: Dict[Pos, int] = getattr(self, "history", {})

        def hardness(net):
            src = self.pl.net_sources.get(net)
            sinks = self.pl.net_sinks.get(net, [])
            if not src or not sinks:
                return (0, 0)
            span = max(abs(src[0]-s[0])+abs(src[2]-s[2]) for s in sinks)
            return (len(sinks), span)

        order = sorted(self.pl.net_sinks.keys(), key=hardness, reverse=True)
        best_result = None
        best_failed = None

        for it in range(max_iters):
            # fresh route each iteration
            self.wire_owner.clear()
            result = RouteResult({}, {}, [], self.wire_owner)
            failed = []
            for net in order:
                if not self._route_one(net, result):
                    failed.append(net)

            if best_failed is None or len(failed) < len(best_failed):
                best_failed, best_result = list(failed), result

            if not failed:
                result.failed = []
                return result

            # bump history along each failed net's corridor so contested cells
            # get more expensive and the pack disperses next iteration
            for net in failed:
                src = self.pl.net_sources.get(net)
                for sink in self.pl.net_sinks.get(net, []):
                    if not src:
                        continue
                    x0, z0, x1, z1 = src[0], src[2], sink[0], sink[2]
                    for x in range(min(x0, x1), max(x0, x1) + 1):
                        self.history[(x, 0, z1)] = self.history.get((x, 0, z1), 0) + 2
                    for z in range(min(z0, z1), max(z0, z1) + 1):
                        self.history[(x0, 0, z)] = self.history.get((x0, 0, z), 0) + 2
            # also lightly penalize wherever winners sat, to shake loose
            for pos in self.wire_owner:
                self.history[pos] = self.history.get(pos, 0) + 1

        best_result.failed = best_failed or []
        return best_result


if __name__ == "__main__":
    from placer import place
    # fan-out demo
    nl = {'cells':{
        'n1':{'type':'NOT','inputs':{'A':'x'},'outputs':{'Q':'a'}},
        'n2':{'type':'NOT','inputs':{'A':'x'},'outputs':{'Q':'b'}},
        'or1':{'type':'OR','inputs':{'A':'a','B':'b'},'outputs':{'Q':'y'}},
    },'inputs':['x'],'outputs':['y']}
    pl = place(nl)
    r = MazeRouter(pl).route()
    print("maze router:", {k: len(v) for k, v in r.wires.items()}, "failed:", r.failed)
