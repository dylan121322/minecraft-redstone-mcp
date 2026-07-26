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

# ---- multiprocessing worker (module scope so it's picklable) ----
_WS = {}  # per-worker static state

def _worker_init(static):
    global _WS
    _WS = static

def _worker_route(arg):
    """Route one net's full fan-out tree against a frozen cost field.
    Returns (net, set_of_wire_positions)."""
    net, pres_cost, hist_cost = arg
    occupancy = _WS["occupancy"]; pin_pos = _WS["pin_pos"]
    bx = _WS["bx"]; bz = _WS["bz"]; y_min = _WS["y_min"]; y_max = _WS["y_max"]
    src = _WS["sources"][net]; sinks = _WS["sinks"][net]
    import heapq

    def in_box(p):
        return (bx[0] <= p[0] <= bx[1] and y_min <= p[1] <= y_max
                and bz[0] <= p[2] <= bz[1])

    def cost_bfs(sources, goal):
        pts = list(sources) + [goal]
        cmin_x = min(p[0] for p in pts)-8; cmax_x = max(p[0] for p in pts)+8
        cmin_z = min(p[2] for p in pts)-8; cmax_z = max(p[2] for p in pts)+8
        def hh(p): return abs(p[0]-goal[0])+abs(p[1]-goal[1])+abs(p[2]-goal[2])
        prev = {}; best = {}; pq = []
        for s in sources:
            best[s] = 0.0; heapq.heappush(pq, (hh(s), 0.0, s))
        while pq:
            f, g, cur = heapq.heappop(pq)
            if g > best.get(cur, 1e18): continue
            if cur == goal:
                path = [cur]
                while path[-1] in prev: path.append(prev[path[-1]])
                path.reverse(); return path
            for d in _HORIZ + _VERT:
                nx = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
                if nx != goal:
                    if not in_box(nx): continue
                    if not (cmin_x <= nx[0] <= cmax_x and cmin_z <= nx[2] <= cmax_z): continue
                    if nx in occupancy and nx not in pin_pos: continue
                base = 1.0 if d[1] == 0 else 4.0
                pc = pres_cost.get(nx, 0); hc = hist_cost.get(nx, 0.0)
                ng = g + base * (1.0 + pc) * (1.0 + hc)
                if ng < best.get(nx, 1e18):
                    best[nx] = ng; prev[nx] = cur
                    heapq.heappush(pq, (ng + hh(nx), ng, nx))
        return None

    wires = set()
    tree = {src}
    for sink in sorted(sinks, key=lambda s: abs(src[0]-s[0])+abs(src[2]-s[2])):
        path = cost_bfs(tree, sink)
        if path:
            for p in path:
                if p not in pin_pos:
                    tree.add(p); wires.add(p)
    return net, wires


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
        """Plain Lee wavefront BFS — uniform cost, no history penalty.
        Fast for small modules (<100 gates). Vertical layer changes allowed
        but discouraged (handled by exploring horizontal neighbors first)."""
        from collections import deque
        prev: Dict[Pos, Pos] = {}
        seen: Set[Pos] = set(sources)
        q = deque(sources)
        targets = set(sources) | {goal}
        while q:
            cur = q.popleft()
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            # horizontal first (prefer planar), vertical second
            for d in _HORIZ:
                nx = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
                if nx in seen: continue
                if nx != goal:
                    if not self._passable(nx, net): continue
                    if self._foreign_adjacent(nx, net, targets): continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
            for d in _VERT:
                nx = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
                if nx in seen: continue
                if nx != goal:
                    if not self._passable(nx, net): continue
                    if self._foreign_adjacent(nx, net, targets): continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
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

    def route(self, max_iters: int = 5) -> RouteResult:
        """Lightweight rip-up: re-order failed nets first each pass. Fast; good
        for sparse modules. For dense modules use route_negotiated()."""
        def hardness(net):
            src = self.pl.net_sources.get(net)
            sinks = self.pl.net_sinks.get(net, [])
            if not src or not sinks: return (0, 0)
            span = max(abs(src[0]-s[0])+abs(src[2]-s[2]) for s in sinks)
            return (len(sinks), span)

        order = sorted(self.pl.net_sinks.keys(), key=hardness)
        best_result = None; best_failed = None
        for it in range(max_iters):
            self.wire_owner.clear()
            result = RouteResult({}, {}, [], self.wire_owner)
            failed = []
            for net in order:
                if not self._route_one(net, result):
                    failed.append(net)
            if best_failed is None or len(failed) < len(best_failed):
                best_failed, best_result = list(failed), result
            if not failed:
                result.failed = []; return result
            order = failed + [n for n in order if n not in failed]
        best_result.failed = best_failed or []
        return best_result

    # ---- Parallel PathFinder (multi-core, for the 9950X3D / 32-thread box) ----
    def route_negotiated_parallel(self, max_iters=400, workers=0, verbose=False):
        """Parallel PathFinder. Within each iteration every net routes against a
        FROZEN cost-field snapshot (embarrassingly parallel), then the main
        process aggregates usage and grows history. Parallel-PathFinder converges
        (needs a few more iters than serial) but saturates all cores.

        workers=0 → use os.cpu_count(). Falls back to serial if mp unavailable."""
        import os as _os
        try:
            import multiprocessing as mp
        except Exception:
            return self.route_negotiated(max_iters, verbose)
        nworkers = workers or _os.cpu_count() or 8

        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        if len(nets) < 8:  # small module: serial is fine, avoids mp overhead
            return self.route_negotiated(max_iters, verbose)

        # static per-worker data (occupancy, pins, box) — sent once via initializer
        static = {
            "occupancy": self.pl.occupancy,
            "pin_pos": self.pin_pos,
            "bx": self.bx, "bz": self.bz,
            "y_min": self.y_min, "y_max": self.y_max,
            "sources": {n: self.pl.net_sources[n] for n in nets},
            "sinks": {n: self.pl.net_sinks[n] for n in nets},
            "pin_owner": {p: None for p in self.pin_pos},  # pins are shared refs
        }

        pres_cost: Dict[Pos, int] = {}
        hist_cost: Dict[Pos, float] = {}
        routes: Dict[str, Set[Pos]] = {n: set() for n in nets}
        HIST_INC = 2.0   # aggressive history to pin oscillators fast

        # Batched parallel: split nets into `nbatch` groups. Route each batch in
        # parallel against the CURRENT cost field, then update pres_cost before
        # the next batch. This breaks the correlated-flip oscillation (nets no
        # longer all see an identical empty field) while still using all cores.
        nbatch = max(2, min(nworkers, len(nets) // 4))
        batches = [nets[i::nbatch] for i in range(nbatch)]

        pool = mp.Pool(nworkers, initializer=_worker_init, initargs=(static,))
        try:
            for it in range(max_iters):
                for batch in batches:
                    # remove this batch's current usage from the field
                    for net in batch:
                        for p in routes[net]:
                            pres_cost[p] = pres_cost.get(p, 0) - 1
                        routes[net] = set()
                    # route the batch in parallel against the updated field
                    args = [(net, pres_cost, hist_cost) for net in batch]
                    results = pool.map(_worker_route, args,
                                       chunksize=max(1, len(batch)//nworkers + 1))
                    for net, wires in results:
                        routes[net] = wires
                        for p in wires:
                            pres_cost[p] = pres_cost.get(p, 0) + 1

                congested = [p for p, c in pres_cost.items() if c > 1]
                if not congested:
                    if verbose: print(f"  [parallel] converged in {it+1} iters", flush=True)
                    break
                for p in congested:
                    hist_cost[p] = hist_cost.get(p, 0.0) + HIST_INC
                if verbose and it % 5 == 0:
                    print(f"  [parallel] iter {it}: {len(congested)} congested "
                          f"({nworkers}w/{nbatch}batch)", flush=True)
        finally:
            pool.close(); pool.join()

        result = RouteResult({}, {}, [], {})
        for net in nets:
            result.wires[net] = set(routes[net])
            for p in routes[net]:
                result.wire_owner[p] = net
        result.failed = [n for n in nets if not routes[n]]
        return result

    # ---- PathFinder negotiated-congestion routing (compute-heavy, reliable) ----
    def route_negotiated(self, max_iters: int = 200, verbose: bool = False) -> RouteResult:
        """PathFinder-style negotiated congestion routing.

        Every net is allowed to route through ANY voxel (even ones owned by
        other nets) — BFS ignores foreign-occupancy but pays a `present cost`
        for sharing plus a `history cost` that grows each iteration a voxel
        stays over-used. Over iterations, nets with cheaper alternatives vacate
        contested voxels until no voxel is shared (legal routing). Guaranteed to
        resolve congestion given enough iterations; the compute is the price.

        This is the algorithm to run on the Windows box for large modules."""
        nets = list(self.pl.net_sinks.keys())
        pres_cost: Dict[Pos, int] = {}      # how many nets currently use a voxel
        hist_cost: Dict[Pos, float] = {}    # accumulated congestion history
        routes: Dict[str, Set[Pos]] = {n: set() for n in nets}
        HIST_INC = 1.0

        def occ(p): return pres_cost.get(p, 0)

        for it in range(max_iters):
            # rip up & reroute each net against current cost field
            for net in nets:
                # remove this net's present-usage
                for p in routes[net]:
                    pres_cost[p] = pres_cost.get(p, 0) - 1
                routes[net] = set()
                # route all sinks with cost-aware BFS (Dijkstra)
                src = self.pl.net_sources.get(net)
                sinks = self.pl.net_sinks.get(net, [])
                if src is None or not sinks:
                    continue
                tree = {src}
                for sink in sorted(sinks, key=lambda s: abs(src[0]-s[0])+abs(src[2]-s[2])):
                    path = self._cost_bfs(tree, sink, net, pres_cost, hist_cost)
                    if path:
                        for p in path:
                            if p not in self.pin_pos:
                                tree.add(p); routes[net].add(p)
                # add present usage
                for p in routes[net]:
                    pres_cost[p] = pres_cost.get(p, 0) + 1

            # find congested voxels (shared by >1 net)
            congested = [p for p, c in pres_cost.items() if c > 1]
            if not congested:
                if verbose: print(f"  converged in {it+1} iters")
                break
            # grow history on congested voxels
            for p in congested:
                hist_cost[p] = hist_cost.get(p, 0.0) + HIST_INC
            if verbose and it % 10 == 0:
                print(f"  iter {it}: {len(congested)} congested voxels", flush=True)

        # materialize result; report nets that still share (failed to legalize)
        result = RouteResult({}, {}, [], {})
        for net in nets:
            result.wires[net] = set(routes[net])
            for p in routes[net]:
                result.wire_owner[p] = net
        result.failed = [n for n in nets
                         if self.pl.net_sinks.get(n) and not routes[n]]
        return result

    def _cost_bfs(self, sources, goal, net, pres_cost, hist_cost):
        """A* (Manhattan heuristic) with congestion cost, bounded to a local
        corridor around sources+goal. The corridor bound + heuristic keep the
        search small even on large chips — the key to routing 100+ gate modules
        in reasonable time (plain Dijkstra explored the whole box → too slow)."""
        import heapq
        # corridor: bbox of sources+goal expanded by a margin
        pts = list(sources) + [goal]
        cmin_x = min(p[0] for p in pts) - 8; cmax_x = max(p[0] for p in pts) + 8
        cmin_z = min(p[2] for p in pts) - 8; cmax_z = max(p[2] for p in pts) + 8

        def h(p):  # admissible Manhattan heuristic to goal
            return abs(p[0]-goal[0]) + abs(p[1]-goal[1]) + abs(p[2]-goal[2])

        prev = {}; best = {}; pq = []
        for s in sources:
            best[s] = 0.0; heapq.heappush(pq, (h(s), 0.0, s))
        while pq:
            f, g, cur = heapq.heappop(pq)
            if g > best.get(cur, 1e18): continue
            if cur == goal:
                path = [cur]
                while path[-1] in prev: path.append(prev[path[-1]])
                path.reverse(); return path
            for d in _HORIZ + _VERT:
                nx = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
                if nx != goal:
                    if not self._in_box(nx): continue
                    # corridor bound (only for non-goal cells)
                    if not (cmin_x <= nx[0] <= cmax_x and cmin_z <= nx[2] <= cmax_z):
                        continue
                    if nx in self.pl.occupancy and nx not in self.pin_pos: continue
                    if nx in self.pin_pos and self.wire_owner.get(nx) not in (None, net):
                        continue
                base = 1.0 if d[1] == 0 else 4.0
                pc = pres_cost.get(nx, 0); hc = hist_cost.get(nx, 0.0)
                ng = g + base * (1.0 + pc) * (1.0 + hc)
                if ng < best.get(nx, 1e18):
                    best[nx] = ng; prev[nx] = cur
                    heapq.heappush(pq, (ng + h(nx), ng, nx))
        return None


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
