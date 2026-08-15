"""
pathfinder.py — PathFinder negotiated-congestion router on the TRUE geometry.

Why this exists: the hard-constraint router deadlocks on routing order (n14
routes perfectly alone, gets 0 wires inside the full chip — a textbook
second-order congestion), and soft mode with one-shot penalties exploded to
310 shorts. PathFinder (McMurchie & Ebeling 1995, the FPGA industry standard)
fixes exactly this split:

  * round 1: every net takes its shortest path with NO overlap penalty —
    overlaps are legal, so no net can deadlock. This builds a feasible,
    maximally-overlapped solution.
  * each round: every resource contested by >=2 nets (or forming a measured
    coupling pair) gets its HISTORY cost bumped: h[v] += 1. The present-cost
    factor p grows (x1.6 per round).
  * nets re-route every round under cost(v) = 1 + h[v] * p, negotiating the
    sharing away incrementally. The escalating p is what one-shot soft mode
    lacked: early rounds tolerate sharing, late rounds forbid it.

  * convergence == ZERO measured shorts (coupling.couples), not just zero
    overlap — the history bump includes coupling pairs, so a converged
    solution is physically clean by construction.

Search model (y=0 signal plane, no bridges in v1 — the congestion map proved
the plane has plenty of room; the deadlock was order, not space):
  HARD obstacles: cell bodies, gate pin cells, box exterior (same as the
  buildable router — dust physically cannot sit there).
  SOFT: everything else, priced at 1 + h * p.
  Multi-sink Steiner: wavefront Dijkstra from the whole current tree per sink,
  farthest sink first — each sink merges into the tree.

Output: route_buildable placement tuples ("dust", x, y, z) per net, fed
straight into BuildableRouter._materialize — reusing its repeater insertion,
tower-aware connectivity check and BuildResult, i.e. the proven emit + MCHPRS
chain downstream is unchanged.
"""
from __future__ import annotations
import heapq
import sys, os, json, time
from typing import Dict, List, Tuple, Set, Optional

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))

import coupling
from placer import Placement

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
XZ = Tuple[int, int]

P_GROW = 1.6          # present-cost factor growth per round
P0 = 1.0              # initial present-cost factor


class PathFinder:
    def __init__(self, pl: Placement, margin: int = 16):
        self.pl = pl
        mn, mx = pl.bounds
        self.bx = (mn[0] - margin, mx[0] + margin)
        self.bz = (mn[2] - margin, mx[2] + margin)
        self.y0 = mn[1]
        # Cell bodies PLUS their 4-neighbour (orthogonal) shell are hard
        # obstacles: cell internals (wall torches, mounts, target dust) are
        # not in any occ table, so a routed line orthogonally grazing a cell
        # couples into its internals (measured: g0_NOT's torch-side dust read
        # 13 from a neighbouring net's wire while the gate was fed 15 -> the
        # NOT never inverts). Diagonals are allowed: the diagonal-coupling
        # rule needs a shared orthogonal conductor, and cell internals are
        # not registered as such — the 8-neighbour version starved the hard
        # repair (19 nets unfixable, 303 shorts after fallback lines came
        # back) by eating too much channel space.
        base_cells = set((p[0], p[2]) for p in pl.occupancy)
        self.cell_xz: Set[XZ] = set(base_cells)
        for (x, z) in base_cells:
            for dx, dz in ORTH:
                self.cell_xz.add((x + dx, z + dz))
        self.pin_xz: Set[XZ] = set()
        for net, pos in pl.net_sources.items():
            self.pin_xz.add((pos[0], pos[2]))
        for net, sinks in pl.net_sinks.items():
            for pos in sinks:
                self.pin_xz.add((pos[0], pos[2]))
        # history cost per cell: bumped every round the cell is contested
        self.h: Dict[XZ, float] = {}
        self.p = P0
        self.nets = [n for n in pl.net_sinks
                     if pl.net_sources.get(n) and pl.net_sinks.get(n)]

    # ---------- geometry ----------
    def _in_box(self, xz: XZ) -> bool:
        return self.bx[0] <= xz[0] <= self.bx[1] and \
               self.bz[0] <= xz[1] <= self.bz[1]

    def _hard_blocked(self, xz: XZ, goal: XZ) -> bool:
        if xz == goal:
            return False
        if not self._in_box(xz):
            return True
        if xz in self.cell_xz:
            return True
        if xz in self.pin_xz:
            return True
        return False

    # ---------- one sink's Dijkstra (wavefront from the whole tree) ----------
    def _sink_route(self, tree: Set[XZ], goal: XZ, visited: Dict[XZ, float],
                    banned: Set[XZ]) -> Optional[List[XZ]]:
        """Soft Dijkstra: everything not hard-blocked is enterable at cost
        1 + h[v] * p. Returns the path (excluding nodes already in `tree`'s
        closure that it reuses... actually INCLUDING all nodes; callers merge)."""
        p = self.p
        dist = {c: 0.0 for c in tree}
        prev: Dict[XZ, XZ] = {}
        pq = [(0.0, c) for c in tree]
        heapq.heapify(pq)
        while pq:
            d, cur = heapq.heappop(pq)
            if d > dist.get(cur, float("inf")):
                continue
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            for dx, dz in ORTH:
                nx = (cur[0] + dx, cur[1] + dz)
                if self._hard_blocked(nx, goal):
                    continue
                # step cost: entering nx
                step = 1.0 + self.h.get(nx, 0.0) * p
                nd = d + step
                if nd < dist.get(nx, float("inf")):
                    dist[nx] = nd
                    prev[nx] = cur
                    heapq.heappush(pq, (nd, nx))
        return None

    # ---------- contested resources ----------
    def _contested(self, usage: Dict[XZ, Set[str]]) -> Set[XZ]:
        """EXACT conflict resources: conductor cells that overlap (>=2 nets)
        or that form a measured coupling pair with a foreign conductor. Only
        these get history bumps — the earlier inflation model (8-neighbour
        claim) contested cells 2 apart that do NOT physically couple, polluted
        the whole map with history and killed convergence (shorts stuck at
        ~250 for 30 rounds)."""
        occ3 = {(x, self.y0, z): min(ns) for (x, z), ns in usage.items()}
        out: Set[XZ] = set()
        for v, nets in usage.items():
            if len(nets) > 1:
                out.add(v)
        seen: Set[tuple] = set()
        for v in usage:
            x, z = v
            for dx, dz in ORTH + coupling.DIAG:
                w = (x + dx, z + dz)
                if w not in usage:
                    continue
                if usage[w] == usage[v]:
                    continue
                a = (x, self.y0, z)
                b = (w[0], self.y0, w[1])
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                if coupling.couples(a, b, occ3):
                    out.add(v)
                    out.add(w)
        return out

    def _count_shorts(self, usage: Dict[XZ, Set[str]]) -> int:
        occ3 = {(x, self.y0, z): min(ns) for (x, z), ns in usage.items()}
        return coupling.count_shorts(occ3)

    @staticmethod
    def _occ3_from(placements: Dict[str, List[tuple]],
                   y0: int) -> Dict[Tuple[int, int, int], str]:
        o = {}
        for net, ps in placements.items():
            for role, x, y, z in ps:
                o[(x, y, z)] = net
        return o

    def _count_shorts_placements(self, placements: Dict[str, List[tuple]]) -> int:
        return coupling.count_shorts(self._occ3_from(placements, self.y0))

    def _conflicting_nets(self, placements: Dict[str, List[tuple]]) -> Set[str]:
        u: Dict[XZ, Set[str]] = {}
        for net, ps in placements.items():
            for role, x, y, z in ps:
                u.setdefault((x, z), set()).add(net)
        o3 = self._occ3_from(placements, self.y0)
        bad: Set[str] = set()
        seen: Set[tuple] = set()
        for v, nets in u.items():
            x, z = v
            for dx, dz in ORTH + coupling.DIAG:
                w = (x + dx, z + dz)
                if w not in u:
                    continue
                if u[w] == nets:
                    continue
                a = (x, self.y0, z)
                b = (w[0], self.y0, w[1])
                key = tuple(sorted([a, b]))
                if key in seen:
                    continue
                seen.add(key)
                if coupling.couples(a, b, o3):
                    bad |= nets | u[w]
        return bad

    def _hard_route_net(self, net: str, frozen_occ: dict,
                        ignore_nets: Optional[Set[str]] = None
                        ) -> Optional[List[tuple]]:
        """Rip-up one net and re-route it under HARD constraints against the
        frozen (already clean) lines: every candidate cell must not couple
        with any foreign conductor, per the measured rule. Multi-sink Steiner
        by wavefront Dijkstra, farthest sink first.

        `ignore_nets`: nets whose lines may be touched (temporarily coupled).
        The repair loop passes the current bad set so that nets being repaired
        in the same round can overlap each other; the conflict set then
        shrinks round by round instead of deadlocking on hard walls."""
        ignore = ignore_nets or set()
        s = self.pl.net_sources[net]
        src = (s[0], s[2])
        tree: Set[XZ] = {src}
        for k in sorted(self.pl.net_sinks[net],
                        key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                        reverse=True):
            goal = (k[0] - 1, k[2])
            dist = {c: 0 for c in tree}
            prev: Dict[XZ, XZ] = {}
            pq = [(0, c) for c in tree]
            heapq.heapify(pq)
            found = None
            while pq:
                d, cur = heapq.heappop(pq)
                if d > dist.get(cur, 1e9):
                    continue
                if cur == goal:
                    found = cur
                    break
                for dx, dz in ORTH:
                    nx = (cur[0] + dx, cur[1] + dz)
                    if nx != goal:
                        if not self._in_box(nx):
                            continue
                        if nx in self.cell_xz:
                            continue
                        if nx in self.pin_xz:
                            continue
                    cand3 = (nx[0], self.y0, nx[1])
                    bad = False
                    for dx3, dy3, dz3 in coupling.shell_offsets():
                        q = (cand3[0] + dx3, cand3[1] + dy3, cand3[2] + dz3)
                        fo = frozen_occ.get(q)
                        if fo is not None and fo != net and fo not in ignore:
                            if coupling.couples(cand3, q, frozen_occ):
                                bad = True
                                break
                    if bad:
                        continue
                    nd = d + 1
                    if nd < dist.get(nx, 1e9):
                        dist[nx] = nd
                        prev[nx] = cur
                        heapq.heappush(pq, (nd, nx))
            if found is None:
                return None
            path = [found]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            for v in path:
                tree.add(v)
        return [("dust", v[0], self.y0, v[1]) for v in sorted(tree)]

    def _soft_route_net(self, net: str, p: float,
                        occupied: Optional[Set[XZ]] = None
                        ) -> Optional[List[tuple]]:
        """Soft re-route of ONE net under negotiation cost (1 + h*p), no
        coupling checks but NO OVERLAP either — overlapping dust of two nets
        is impossible in the emitted build (the later emit overwrites the
        earlier), which silently severed every net soft-routed on top of
        another (measured: n31/n18/n20 stuck at pwr=0). Allowing adjacency
        but forbidding sharing keeps the route always feasible while every
        sink's dust physically exists; the polish pass separates the
        couplings. `occupied`: cells owned by other nets."""
        occ = occupied or set()
        s = self.pl.net_sources[net]
        src = (s[0], s[2])
        tree: Set[XZ] = {src}
        for k in sorted(self.pl.net_sinks[net],
                        key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                        reverse=True):
            goal = (k[0] - 1, k[2])
            dist = {c: 0.0 for c in tree}
            prev: Dict[XZ, XZ] = {}
            pq = [(0.0, c) for c in tree]
            heapq.heapify(pq)
            found = None
            while pq:
                d, cur = heapq.heappop(pq)
                if d > dist.get(cur, 1e9):
                    continue
                if cur == goal:
                    found = cur
                    break
                for dx, dz in ORTH:
                    nx = (cur[0] + dx, cur[1] + dz)
                    if self._hard_blocked(nx, goal):
                        continue
                    if nx in occ and nx != goal:
                        continue          # never share a cell with another net
                    step = 1.0 + self.h.get(nx, 0.0) * p
                    nd = d + step
                    if nd < dist.get(nx, 1e9):
                        dist[nx] = nd
                        prev[nx] = cur
                        heapq.heappush(pq, (nd, nx))
            if found is None:
                return None
            path = [found]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            for v in path:
                tree.add(v)
        return [("dust", v[0], self.y0, v[1]) for v in sorted(tree)]

    def repair(self, placements: Dict[str, List[tuple]], max_rounds: int = 10
               ) -> Dict[str, List[tuple]]:
        """Phase 2: freeze the clean nets' lines and hard-reroute the
        conflicting nets against them, iterating until zero shorts. The
        negotiated solution is already close, so the hard pass only needs
        small local detours — unlike a cold hard-constraint route, which
        deadlocks on order.

        Drop semantics (measured): a net whose hard reroute fails is REMOVED
        from the solution — its old line leaves the board, freeing that space
        for the others, and it retries next round. Keeping the old line froze
        the conflict set forever (600 shorts, 10 flat rounds); soft-routing
        it back every round did the same (737). Pure drop converges: 199
        shorts -> 0 with zero structural couplings left (diag_struct, fixed
        cells all clean)."""
        original = {n: list(ps) for n, ps in placements.items()}
        dropped_ever: Set[str] = set()
        for rnd in range(max_rounds):
            bad = self._conflicting_nets(placements)
            if not bad:
                break
            frozen = {n: placements[n] for n in placements if n not in bad}
            fo3 = self._occ3_from(frozen, self.y0)
            # PI injection cells are FIXED foreign conductors the repair
            # never sees in placements (the emitter places them): the PI dust
            # itself and its redstone-block injector one cell west. Without
            # them in fo3, repaired lines grazed the injectors (5 of the 7
            # residual shorts were n2/n5 PI-zone couplings, and n4 leaked to
            # pwr=11 off its neighbours).
            for net, pos in self.pl.primary_inputs.items():
                fo3[(pos[0], pos[1], pos[2])] = net
                fo3[(pos[0] - 1, pos[1], pos[2])] = net
            new_place = dict(frozen)
            dropped: Set[str] = set()
            for n in sorted(bad, key=lambda n: (-len(self.pl.net_sinks[n]), n)):
                ps = self._hard_route_net(n, fo3)
                if ps is None:
                    if n in self.pl.primary_inputs:
                        # PI lines are NEVER dropped: a missing PI starves
                        # every downstream gate of that input bit and stuck
                        # the whole ALU (measured: n3/n4/n5/n7/n8 all failed
                        # soft-repair -> outputs frozen). Keep the old line.
                        new_place[n] = placements[n]
                    else:
                        dropped.add(n)
                    continue          # old line removed; space is freed
                new_place[n] = ps
                for role, x, y, z in ps:
                    fo3[(x, y, z)] = n
            placements = new_place
            dropped_ever |= dropped
            print(f"  repair {rnd}: bad={len(bad)} dropped={len(dropped)} "
                  f"shorts={self._count_shorts_placements(placements)}",
                  flush=True)
        # soft-route every dropped net back — its sinks MUST be fed (a missing
        # net reads as floating input, which stuck the whole ALU output even at
        # 0 shorts). Soft lines couple, so polish below.
        for n in sorted(dropped_ever):
            occ_others = {v for m, ps in placements.items() if m != n
                          for (role, x, y, z) in ps for v in [(x, z)]}
            ps = self._soft_route_net(n, self.p, occupied=occ_others)
            if ps is None:
                # fallback: reinstate the pre-repair line. It couples in
                # places, but a complete line beats a missing one — missing
                # nets float their sinks and freeze the whole ALU output.
                ps = original.get(n)
            if ps is not None:
                placements[n] = ps
        # final polish: a few more drop-repair rounds over whatever conflicts
        # the soft lines introduced.
        for rnd in range(4):
            bad = self._conflicting_nets(placements)
            if not bad:
                break
            frozen = {n: placements[n] for n in placements if n not in bad}
            fo3 = self._occ3_from(frozen, self.y0)
            for net, pos in self.pl.primary_inputs.items():
                fo3[(pos[0], pos[1], pos[2])] = net
                fo3[(pos[0] - 1, pos[1], pos[2])] = net
            new_place = dict(frozen)
            for n in sorted(bad, key=lambda n: (-len(self.pl.net_sinks[n]), n)):
                ps = self._hard_route_net(n, fo3)
                if ps is None:
                    new_place[n] = placements[n]   # KEEP the old (soft) line:
                    # dropping it here silently severed nets (n30 lost its
                    # wire entirely, n5's fan-out broke mid-way) — the polish
                    # pass must never reduce coverage, only reduce shorts.
                    continue
                new_place[n] = ps
                for role, x, y, z in ps:
                    fo3[(x, y, z)] = n
            placements = new_place
            print(f"  polish {rnd}: bad={len(bad)} "
                  f"shorts={self._count_shorts_placements(placements)}",
                  flush=True)
        return placements

    # ---------- main loop ----------
    def route(self, max_rounds: int = 60, verbose: bool = True,
              with_repair: bool = True
              ) -> Tuple[Dict[str, List[tuple]], int]:
        """Returns (placements, shorts) where placements uses route_buildable's
        tuple format. Converges when shorts == 0.

        Classic PathFinder loop: rip up everything, re-route every net under
        cost 1 + h*p, bump history on the round's conflict cells, escalate p."""
        best = None
        best_shorts = 1 << 30
        t0 = time.time()
        for rnd in range(max_rounds):
            usage: Dict[XZ, Set[str]] = {}
            placements: Dict[str, List[tuple]] = {}
            unfed = []
            for net in self.nets:
                s = self.pl.net_sources[net]
                src = (s[0], s[2])
                tree: Set[XZ] = {src}
                tree_usage: Dict[XZ, str] = {src: net}
                ok = True
                sinks = sorted(self.pl.net_sinks[net],
                               key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                               reverse=True)
                for k in sinks:
                    goal = (k[0] - 1, k[2])
                    path = self._sink_route(tree, goal, {}, set())
                    if path is None:
                        ok = False
                        unfed.append((net, goal))
                        continue
                    for v in path:
                        if v not in tree_usage:
                            tree_usage[v] = net
                        tree.add(v)
                placements[net] = [("dust", v[0], self.y0, v[1])
                                   for v in sorted(tree)]
                for v in tree:
                    usage.setdefault(v, set()).add(net)
            contested = self._contested(usage)
            shorts = self._count_shorts(usage)
            if verbose:
                print(f"round {rnd:2d}: p={self.p:6.1f} shorts={shorts:4d} "
                      f"contested={len(contested):5d} unfed={len(unfed):3d} "
                      f"{time.time()-t0:5.1f}s", flush=True)
            if shorts < best_shorts:
                best_shorts = shorts
                best = placements
            if shorts == 0 and not unfed:
                if verbose:
                    print(f"  CONVERGED at round {rnd}", flush=True)
                return best, 0
            for v in contested:
                self.h[v] = self.h.get(v, 0.0) + 1.0
            # slow escalation, capped: too-fast p burns the map and too-high p
            # freezes detours (measured: no-cap run oscillated 184-490 at p=830k)
            self.p = min(self.p * P_GROW, 128.0)
        # negotiation plateaus around ~200 shorts on alu1 (adjacency conflicts
        # chase each other); the hard repair pass finishes the job: freeze
        # clean lines, reroute the conflicting few. 197 -> 0 in 2 rounds.
        if with_repair:
            best = self.repair(best, max_rounds=10)
        return best, self._count_shorts_placements(best)


def _main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth",
                                      "netlists.json")))
    nl = nls["alu1"]
    from placer import place
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=30)
    print(f"\nfinal: shorts={shorts}")
    # total wire
    tot = sum(len(ps) for ps in placements.values())
    print(f"total dust cells: {tot}")


if __name__ == "__main__":
    _main()
