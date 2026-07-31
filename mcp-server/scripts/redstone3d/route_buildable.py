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
# Sink connections longer than this skip the y=0 plane and go straight to a cross
# layer. Keeps the signal plane free for local wiring and descent corridors.
# Disabled (very large): forcing long sink connections onto a cross layer did
# raise the routed count (24 -> 26) but WRECKED electrical correctness — only
# 16 of 26 links still responded, versus 24 of 24 when long hauls stay on y=0.
# Long cross runs are simply less reliable than the signal plane, so keep them
# off unless a future change makes cross runs as robust as y0.
LONG_HAUL = 10 ** 9
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
        self.owner2: Dict[XZ, str] = {}    # legacy single cross-plane (unused now)
        self.support1: Dict[XZ, str] = {}  # y=1 support/block owner
        # Per-net cross plane: each bridged net gets its OWN cross Y (y4, y6, ...)
        # so different nets' cross wires are on different layers and can never be
        # adjacent => cross-plane shorts are structurally impossible. owner_cross
        # is indexed by cross-Y then xz. net_cross_y maps a net to its layer.
        self.owner_cross: Dict[int, Dict[XZ, str]] = {}
        self.net_cross_y: Dict[str, int] = {}
        # negotiated-congestion history: per-cell penalty accumulated across
        # rip-up rounds. A cell that hosted a short in a prior round gets a
        # higher cost, so nets negotiate away from contested cells over rounds.
        self.hist0: Dict[XZ, float] = {}   # y=0 plane history cost
        self.histC: Dict[XZ, float] = {}   # cross (y4) plane history cost

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

    # ---------- y=0 planar weighted shortest path (negotiated) ----------
    def _plane_bfs(self, tree: Set[XZ], goal: XZ, net: str,
                   soft: bool = False) -> Optional[List[XZ]]:
        """Dijkstra on the y=0 plane. HARD blocks: out-of-box, cell body, pin
        transit. SOFT costs (when soft=True, the negotiated mode): stepping onto
        a foreign wire, or adjacent to a foreign wire/pin, costs a large penalty
        plus the cell's accumulated history — allowed but discouraged, so nets
        negotiate apart across rip-up rounds. soft=False reproduces the strict
        one-shot behaviour (foreign adjacency forbidden)."""
        import heapq
        BASE = 1.0
        ADJ_PEN = 40.0      # grazing a foreign wire/pin
        OVER_PEN = 120.0    # sharing a foreign wire cell
        dist = {c: 0.0 for c in tree}
        prev: Dict[XZ, XZ] = {}
        pq = [(0.0, c) for c in tree]
        heapq.heapify(pq)
        while pq:
            d, cur = heapq.heappop(pq)
            if cur == goal:
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                return path
            if d > dist.get(cur, float("inf")):
                continue
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx != goal:
                    if not self._in_box(nx):
                        continue
                    if nx in self.cell_xz:
                        continue
                    if nx in self.pin_net:          # never transit through a pin
                        continue
                    o = self.owner0.get(nx)
                    adj_f = self._foreign_plane(nx, net, self.owner0) or \
                            self._foreign_pin_adj(nx, net, goal)
                    # HARD constraints always (no overlap, no grazing) — keeps
                    # shorts at 0. History is a soft COST that steers this net's
                    # own path off cells that blocked others, without ever
                    # allowing a real conflict.
                    if o is not None and o != net:
                        continue
                    if adj_f:
                        continue
                    step = BASE + self.hist0.get(nx, 0.0)
                nd = d + (BASE if nx == goal else step)
                if nd < dist.get(nx, float("inf")):
                    dist[nx] = nd; prev[nx] = cur
                    heapq.heappush(pq, (nd, nx))
        return None

    # ---------- top-level (negotiated rip-up) ----------
    def route(self, verbose: bool = False, max_rounds: int = 40) -> BuildResult:
        """Negotiated rip-up. Every round rips up and reroutes ALL nets under the
        HARD (non-overlapping) constraints; congestion is negotiated via (a) the
        routing ORDER — nets that failed last round go FIRST this round so they
        seize their scarce escape channels before flexible nets — and (b) a
        per-cell history penalty that pushes the *competitors* off contested
        cells. No soft overlap is ever allowed (that made shorts explode); only
        order + history move, so shorts stay 0 while unrouted nets drop to 0."""
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]

        def span(n):
            s = self.pl.net_sources[n]; ks = self.pl.net_sinks[n]
            return max(abs(s[0]-k[0])+abs(s[2]-k[2]) for k in ks)
        base_order = sorted(nets, key=lambda n: (len(self.pl.net_sinks[n]), span(n)))

        best_res = None; best_key = (1 << 30, 1 << 30)
        priority: List[str] = []          # nets to route first (grew from failures)
        for rnd in range(max_rounds):
            order = priority + [n for n in base_order if n not in priority]
            res = self._route_once(order, soft=False, verbose=verbose and rnd == 0)
            shorts, _ = self._count_shorts(res)
            # A short makes the whole module compute WRONG answers, while an
            # unrouted net only leaves a feature missing — so shorts dominate the
            # comparison. (Ranking by failed-count first once picked a 3-failed /
            # 5-short round over a 5-failed / 0-short one.)
            key = (shorts, len(res.failed))
            if verbose and (rnd < 3 or key < best_key):
                print(f"  round {rnd}: failed={len(res.failed)} shorts={shorts} "
                      f"order_head={order[:3]}", flush=True)
            if key < best_key:
                best_key = key; best_res = res
            if shorts == 0 and not res.failed:
                if verbose:
                    print(f"  converged at round {rnd}", flush=True)
                return res
            # Priority = THIS round's failures only (an ever-growing priority list
            # made the order thrash: previously-failed nets kept hogging the front
            # and displaced others, so failed oscillated 7->11->12->4).
            priority = list(res.failed)
            # present-cost escalation: the penalty applied to a failed net's
            # blockers grows with the round, so blockers are pushed off contested
            # channels ever more strongly until the ordering stabilises.
            self._bump_blocker_history(res, weight=8.0 * (1 + rnd))
        return best_res

    def _route_once(self, nets, soft: bool, verbose: bool = False) -> BuildResult:
        # fresh occupancy each round (rip-up everything)
        self.owner0 = {}; self.owner2 = {}; self.support1 = {}
        self.owner_cross = {}; self.net_cross_y = {}
        self.net_paths = {}
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
                # route to the pin's WEST FEED cell, not the pin itself: the pin
                # is a west-facing repeater and only conducts from that one cell.
                goal = (k[0] - 1, k[2])
                # LONG HAULS GO UPSTAIRS. Measured on alu1: 24 of 47 sink
                # connections are >40 cells and the 5 unroutable nets are exactly
                # the longest ones (up to 257 cells). Dragging those across y0
                # fills the signal plane and blocks other nets' descent
                # corridors, while the cross planes sit almost empty. Sending
                # long runs to a cross layer is both more three-dimensional and
                # SHORTER (the cross plane is open, so the path is near-straight).
                dist = abs(s[0] - k[0]) + abs(s[2] - k[2])
                if dist > LONG_HAUL:
                    need_bridge.append((net, goal))
                    continue
                path = self._plane_bfs(tree, goal, net, soft=soft)
                if path is None:
                    need_bridge.append((net, goal))
                    continue
                # remember this sink's path IN ORDER: repeater orientation must
                # follow the real travel direction, and reconstructing that from
                # the unordered cell set (BFS tree) mis-oriented repeaters on
                # multi-sink nets (n30 had 9 dead repeaters on a 128-cell route).
                self.net_paths.setdefault(net, []).append(list(path))
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
        # assign each bridged net its OWN cross layer (y4, y8, y12, ...): even
        # torch count (cross_y%4==0 => cross_y/2 even => non-inverting) AND
        # different nets' cross planes >=4 apart => never adjacent => 0 cross
        # shorts by construction.
        bridge_nets = []
        for net, _g in sorted(need_bridge, key=lambda ng: ng[0]):
            if net not in bridge_nets:
                bridge_nets.append(net)
        # COLOR bridge nets so non-conflicting ones SHARE a cross layer, keeping
        # cross Y (and thus descent depth) low. Two bridge nets conflict if their
        # source→sink x-spans overlap (their cross runs could then be adjacent on
        # a shared layer). Greedy graph colouring; colour c -> cross Y = y0+4*c.
        def xspan(n):
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            return (min(xs), max(xs))
        # Cross layers are assigned ON DEMAND, lowest first: every bridged net
        # tries y0+4 and only moves up when its cross route actually collides
        # with a net already on that layer. Pre-colouring by x-span overlap was
        # far too pessimistic (all long nets "overlap", so n2 landed on y17 —
        # and since the descent staircase is as long as the layer is high, a deep
        # layer forces a long cross run AND a long descent: the opposite of
        # minimal. The router retries _bridge per layer, so correctness is kept.
        for net in bridge_nets:
            self.net_cross_y.setdefault(net, y0 + 4)
        for net, goal in sorted(need_bridge, key=lambda ng: ng[0]):
            # try the lowest cross layer first, stepping up (+4 Y each time, so
            # the torch count stays even => non-inverting) only when this layer
            # is genuinely blocked. Keeps hops shallow and short.
            gadget = None
            saved = self.net_cross_y.get(net, y0 + 4)
            for attempt in range(6):
                self.net_cross_y[net] = saved + 4 * attempt
                gadget = self._bridge(net, goal, placements, climbed)
                if gadget:
                    break
                # a failed attempt may have left this net's climb registered
                climbed.pop(net, None)
            if gadget:
                placements[net].extend(gadget)
                bridges[net] += 1
        return self._materialize(nets, placements, bridges)

    # a repeater only connects along its facing axis (front/back); its sides and
    # diagonals are electrically isolated (verified test_rep_side). Map facing ->
    # the ONLY two offsets that can short it.
    _REP_AXIS = {"west": {(1, 0), (-1, 0)}, "east": {(1, 0), (-1, 0)},
                 "north": {(0, 1), (0, -1)}, "south": {(0, 1), (0, -1)}}

    def _count_shorts(self, res):
        from route_buildable import _PLANE_SHELL
        owner = dict(res.wire_owner)
        rep_face = {}
        for net, reps in res.repeaters.items():
            for (pos, f) in reps:
                owner[pos] = net; rep_face[pos] = f

        def couples(a, b, off):
            # off is the (dx,dz) from a to b. If a (or b) is a repeater, the
            # coupling only counts along that repeater's facing axis.
            if a in rep_face and off not in self._REP_AXIS[rep_face[a]]:
                return False
            boff = (-off[0], -off[1])
            if b in rep_face and boff not in self._REP_AXIS[rep_face[b]]:
                return False
            return True

        seen = set(); short_cells = set()
        for p, net in owner.items():
            x, y, z = p
            for dx, dz in _PLANE_SHELL:
                q = (x+dx, y, z+dz); o = owner.get(q)
                if o is not None and o != net and couples(p, q, (dx, dz)):
                    k = tuple(sorted([p, q]))
                    if k not in seen:
                        seen.add(k); short_cells.add(p); short_cells.add(q)
            for dy in (1, -1):
                q = (x, y+dy, z); o = owner.get(q)
                if o is not None and o != net:
                    k = tuple(sorted([p, q]))
                    if k not in seen:
                        seen.add(k); short_cells.add(p); short_cells.add(q)
        return len(seen), short_cells

    def _bump_blocker_history(self, res, weight: float = 8.0):
        """For each failed net, penalise the y0 cells inside its source→sink
        bounding box that are currently owned by OTHER nets — those are the
        blockers occupying the escape channels. Higher history makes the blockers
        route around next round, freeing the channel for the failed net (which
        also goes first next round)."""
        for net in res.failed:
            s = self.pl.net_sources[net]
            for k in self.pl.net_sinks[net]:
                x0, x1 = sorted((s[0], k[0]))
                z0, z1 = sorted((s[2], k[2]))
                for xx in range(x0 - 1, x1 + 2):
                    for zz in range(z0 - 1, z1 + 2):
                        o = self.owner0.get((xx, zz))
                        if o is not None and o != net:
                            self.hist0[(xx, zz)] = self.hist0.get((xx, zz), 0.0) + weight
                # Extra pressure on the DESCENT CORRIDORS this sink needs. The
                # remaining failures are all "DESCENT conflict", and static room
                # is plentiful (measured: every sink has a 15-40 cell clear west
                # run) — the lanes are simply taken by nets routed earlier. Making
                # those specific cells expensive is what actually frees a corridor;
                # the coarse bounding-box penalty alone never targeted them.
                gx, gz = k[0], k[2]
                for dz in (0, 1, -1, 2, -2):
                    zz = gz + dz
                    for xx in range(gx - 24, gx):
                        o = self.owner0.get((xx, zz))
                        if o is not None and o != net:
                            self.hist0[(xx, zz)] = \
                                self.hist0.get((xx, zz), 0.0) + weight * 2

    def _net_wire_xzs(self, net, placements) -> Set[XZ]:
        """xz of this net's y=0 dust so far (bridge can start from one)."""
        out = set()
        for pl in placements[net]:
            if pl[0] == "dust" and pl[2] == self.base_y:
                out.add((pl[1], pl[3]))
        s = self.pl.net_sources[net]
        out.add((s[0], s[2]))
        return out

    def _y2_free(self, xz, net, cy):
        """Can net's cross dust occupy xz on cross-Y=cy? Only same-layer foreign
        cross wires matter (different cross layers are >=2 apart in Y => isolated
        like H/V planes). Reject if a foreign cross wire on THIS layer is in the
        8-neighbourhood. y0 crossings are free (different plane)."""
        if not self._in_box(xz):
            return False
        oc = self.owner_cross.setdefault(cy, {})
        o = oc.get(xz)
        if o is not None and o != net:
            return False
        for dx, dz in _PLANE_SHELL:
            o = oc.get((xz[0]+dx, xz[1]+dz))
            if o is not None and o != net:
                return False
        return True

    def _y2_bfs(self, sources, goal, net, cy):
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
                if nx != goal and not self._y2_free(nx, net, cy):
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
        y0 = self.base_y
        cy_cross = self.net_cross_y[net]        # this net's dedicated cross Y
        ncl = (cy_cross - y0) // 2              # torch count (even => cross_y%4==0)
        gx, gz = goal_xz
        p = []
        depth = cy_cross + 1 - y0              # staircase length (dust plane = cross+1)

        if net not in climbed:
            s = self.pl.net_sources[net]
            # MINIMAL HOP: start the climb from the point of the net's ALREADY
            # ROUTED y0 tree that is closest to this sink, not from the source.
            # Climbing at the source made the signal travel the whole way on the
            # cross plane (n8: 133 cross cells for an 8-cell obstacle, n13: 216),
            # which wastes space and multiplies the adjacency surface. The real
            # blockage is only a few cells wide, so we hop just over it.
            anchor = self._extend_toward(net, placements, goal_xz)
            sx, sz = anchor if anchor else (s[0], s[2])
            foot = self._find_foothold(net, (sx, sz))
            if foot is None:
                return None
            (tx, tz), lead = foot
            for (lx, lz) in lead:
                p.append(("dust", lx, y0, lz))
                self.owner0[(lx, lz)] = net
            # The tower's base repeater must FACE the cell the signal arrives
            # from — the last lead cell, or the source itself when the tower sits
            # right next to it. Hard-coding facing=west broke every tower whose
            # foothold was reached from another direction (n8's signal ran north
            # from (0,96) into a west-facing repeater at (0,95) => net dead).
            # Verified tower geometry (test_bridge_gadget / test_via_tower):
            #   drive cell : repeater on the ARRIVAL side, facing the incoming
            #                cell so it reads the lead and drives the tower base
            #   (tx, y0)   : block0
            #   then ncl x { standing torch ; block } climbing +2 Y each
            #   top block at y0+2*ncl == cy_cross, cross dust at cy_cross+1
            # The repeater must NOT sit at (tx, y0) — that is block0's cell; the
            # earlier version overwrote block0 with the repeater, leaving torches
            # stacked on a repeater and the cross dust floating (n8's tower dead).
            prev_cell = lead[-1] if lead else (sx, sz)
            d_in = (tx - prev_cell[0], tz - prev_cell[1])
            face = FLOW_FACING.get(d_in, "west")
            if lead:
                # replace the last lead dust with the driving repeater
                p = [q for q in p if not (q[0] == "dust" and q[1] == prev_cell[0]
                                          and q[3] == prev_cell[1])]
                p.append(("rep", prev_cell[0], y0, prev_cell[1], face))
                self.owner0[prev_cell] = net
            else:
                # tower adjacent to the source: repeater goes between them only if
                # there is room; otherwise drive block0 straight from the source
                # dust (a dust does power an adjacent block enough here).
                pass
            # the tower base cell must be a solid BLOCK; drop any y0 dust the
            # planar routing had placed there (emit writes wires after supports,
            # so a leftover dust would overwrite block0 and kill the tower).
            p = [q for q in p if not (q[0] == "dust" and q[1] == tx
                                      and q[2] == y0 and q[3] == tz)]
            placements[net] = [q for q in placements[net]
                               if not (q[0] == "dust" and q[1] == tx
                                       and q[2] == y0 and q[3] == tz)]
            yy = y0
            for _ in range(ncl):
                p.append(("block", tx, yy, tz))
                p.append(("torch", tx, yy+1, tz))
                yy += 2
            p.append(("block", tx, cy_cross, tz))       # top block
            p.append(("dust", tx, cy_cross+1, tz))      # cross-plane dust
            self.owner0[(tx, tz)] = net
            self.owner_cross.setdefault(cy_cross, {})[(tx, tz)] = net
            self.support1[(tx, tz)] = net
            climbed[net] = {(tx, tz)}
            sz = tz  # cross BFS starts from the tower's z

        # cross-plane BFS to the descent top at (gx-depth, gz), so the +x
        # DESCENT CORRIDOR SEARCH. A fixed west-side +x staircase dies whenever
        # any of its `depth` cells is contested (this was the last failure class:
        # every remaining unrouted net failed with "DESCENT conflict"). Try
        # several corridors — approach from the west (+x descent) or the east
        # (-x descent), each with a small z offset — and take the first one whose
        # whole run is clear. The landing must end orthogonally adjacent to the
        # pin so the pin's west-facing repeater is fed without being covered.
        # Only WEST-side descents: the pin is a west-facing repeater, so the
        # signal must arrive at (gx-1, gz). Landing east of the pin (the old "E"
        # candidates) can never feed it.
        cand = [("W", dz) for dz in (0, 1, -1, 2, -2)]
        chosen = None
        for (side, dz) in cand:
            zz = gz + dz
            if side == "W":
                cells = [(gx - depth + i, zz) for i in range(1, depth + 1)]
                land = (gx - 1, zz)
            else:
                cells = [(gx + depth - i, zz) for i in range(1, depth + 1)]
                land = (gx + 1, zz)
            if any(c in self.cell_xz or c in self.pin_net for c in cells):
                continue
            if any(self._descent_conflict(c, net) for c in cells):
                continue
            # when the corridor runs on an offset row (zz != gz) the landing is
            # not yet beside the pin: add a short y0 jog along z from the landing
            # to the pin's feed cell, and require that jog to be clear too.
            jog = []
            if zz != gz:
                step = 1 if gz > zz else -1
                for t in range(zz + step, gz + step, step):
                    jog.append((land[0], t))
                if any(c in self.cell_xz or c in self.pin_net for c in jog):
                    continue
                if any(self._descent_conflict(c, net) for c in jog):
                    continue
            chosen = (side, zz, cells, jog)
            break
        if chosen is None:
            return None
        side, zz, cells, jog = chosen
        cross_top = (cells[0][0] - (1 if side == "W" else -1), zz)
        path = self._y2_bfs(set(climbed[net]), cross_top, net, cy_cross)
        if path is None:
            return None
        oc = self.owner_cross.setdefault(cy_cross, {})
        # Lay the cross run, inserting a refresh repeater every <=12 cells on a
        # STRAIGHT stretch. Dust loses 1 strength per cell, so an unrefreshed
        # cross run longer than 15 decays to 0 — that killed most bridged nets
        # (n13 routed 241 cells with only the y0 refreshes and read 0 at both
        # sinks). facing = FLOW_FACING[travel] (a repeater reads the side it
        # faces; verified in test_rep_facing).
        # Start the run counter near the refresh threshold so the FIRST straight
        # cell of this cross segment gets a repeater. A later sink's cross path
        # branches off an existing trunk whose signal is already attenuated
        # (n13: the trunk was down to 4 where the second branch began, and the
        # next refresh sat 13 cells further on, so that branch died). Re-driving
        # at the branch point makes every segment start from 15.
        run = MAX_RUN - 2
        for i, (x, z) in enumerate(path):
            if (x, z) in climbed[net]:
                continue
            run += 1
            placed_rep = False
            if run >= MAX_RUN - 1 and 0 < i < len(path) - 1:
                prevc = path[i-1]; nextc = path[i+1]
                came = (x - prevc[0], z - prevc[1])
                leave = (nextc[0] - x, nextc[1] - z)
                f = FLOW_FACING.get(came)
                if f and came == leave:          # straight only
                    p.append(("support", x, cy_cross, z))
                    p.append(("rep", x, cy_cross+1, z, f))
                    placed_rep = True
                    run = 0
            if not placed_rep:
                p.append(("support", x, cy_cross, z))
                p.append(("dust", x, cy_cross+1, z))
            oc[(x, z)] = net; self.support1[(x, z)] = net
            climbed[net].add((x, z))
        # Refresh before the descent: the signal reaches the staircase already
        # attenuated by the cross run (measured on n6: 14 at the tower top, 3 at
        # the end of a 13-cell cross run) and each descent step costs one more, so
        # it died two cells down. Insert the repeater on the SECOND-TO-LAST cross
        # cell — placing it on the last one aimed its output along the cross
        # direction while the path actually turns downward there, which broke more
        # nets than it fixed.
        if len(path) >= 3:
            rc = path[-2]
            came = (rc[0]-path[-3][0], rc[1]-path[-3][1])
            leave = (path[-1][0]-rc[0], path[-1][1]-rc[1])
            f = FLOW_FACING.get(came)
            if f and came == leave:      # straight only
                p = [q for q in p if not (q[0] == "dust" and q[1] == rc[0]
                                          and q[2] == cy_cross+1 and q[3] == rc[1])]
                p.append(("rep", rc[0], cy_cross+1, rc[1], f))

        # emit the staircase along the chosen corridor
        cyy = cy_cross + 1
        for (cx, cz) in cells:
            cyy -= 1
            if cyy > y0:
                p.append(("block", cx, cyy-1, cz)); p.append(("dust", cx, cyy, cz))
            else:
                p.append(("dust", cx, y0, cz))
            self.owner0[(cx, cz)] = net
            self.support1[(cx, cz)] = net
        # y0 jog from the landing row to the pin's feed cell (offset corridors)
        for (jx, jz) in jog:
            p.append(("dust", jx, y0, jz))
            self.owner0[(jx, jz)] = net
        return p

    def _extend_toward(self, net, placements, goal_xz):
        """Push the net's y0 route as CLOSE to goal_xz as the plane allows, lay
        that dust, and return the closest cell reached. The bridge then only has
        to hop the residual gap (measured: n8's real blockage is 8 cells wide,
        while climbing at the source made it fly 133 cells on the cross plane).
        Returns None if nothing was reachable."""
        y0 = self.base_y
        tree = {(p[1], p[3]) for p in placements.get(net, [])
                if p[0] == "dust" and p[2] == y0}
        s = self.pl.net_sources[net]
        tree.add((s[0], s[2]))
        gx, gz = goal_xz
        # Dijkstra-ish BFS over legal y0 cells, tracking the closest approach
        prev = {}; seen = set(tree); q = deque(tree)
        best = min(tree, key=lambda c: abs(c[0]-gx) + abs(c[1]-gz))
        best_d = abs(best[0]-gx) + abs(best[1]-gz)
        while q:
            cur = q.popleft()
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen or not self._in_box(nx):
                    continue
                if nx in self.cell_xz or nx in self.pin_net:
                    continue
                o = self.owner0.get(nx)
                if o is not None and o != net:
                    continue
                if self._foreign_plane(nx, net, self.owner0) or \
                   self._foreign_pin_adj(nx, net, goal_xz):
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
                d = abs(nx[0]-gx) + abs(nx[1]-gz)
                if d < best_d:
                    best_d = d; best = nx
        if best in tree:
            return best
        # lay the dust along the path to `best`
        path = [best]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        for c in path:
            if c in tree or c in self.pin_net:
                continue
            placements[net].append(("dust", c[0], y0, c[1]))
            self.owner0[c] = net
        return best

    def _closest_routed_cell(self, net, placements, goal_xz):
        """The net's already-placed y0 cell nearest to goal_xz (Manhattan). The
        bridge climbs from there so the cross-plane detour spans only the local
        obstacle instead of the whole source→sink distance."""
        cells = [(p[1], p[3]) for p in placements.get(net, [])
                 if p[0] == "dust" and p[2] == self.base_y]
        if not cells:
            return None
        gx, gz = goal_xz
        return min(cells, key=lambda c: abs(c[0]-gx) + abs(c[1]-gz))

    def _find_foothold(self, net, start):
        """2-D BFS on y0 from the source to the nearest cell where a tower can
        stand (repeater base conflict-free). Returns ((tx,tz), lead_path) where
        lead is the y0 dust cells from just after the source to just before the
        foothold, or None if unreachable within a bounded radius. The lead cells
        must themselves be clear (descent_conflict-free) so the escape wire does
        not short."""
        prev = {}; seen = {start}; q = deque([start])
        while q:
            cur = q.popleft()
            # Require at least ONE lead cell between the source and the tower:
            # that cell becomes the driving repeater. A tower placed directly
            # next to the source has nowhere for the repeater to go and its
            # block0 is only weakly powered by the source dust, so the torch
            # ladder never switches (n8's tower sat at (0,95) beside source
            # (0,96) and stayed dead).
            hops = 0
            probe = cur
            while probe in prev:
                probe = prev[probe]; hops += 1
            # hops>=2 so that path = [source, lead.., tower] has at least one
            # intermediate cell: lead = path[1:-1] must be non-empty to host the
            # driving repeater. hops>=1 still allowed a tower directly beside the
            # source (lead empty, block0 undriven, ladder dead).
            if cur != start and hops >= 2 and not self._tower_conflict(cur, net):
                # reconstruct lead (exclude source and foothold)
                path = [cur]
                while path[-1] in prev:
                    path.append(prev[path[-1]])
                path.reverse()
                lead = [c for c in path[1:-1]]
                return cur, lead
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in seen or not self._in_box(nx):
                    continue
                if nx in self.cell_xz or nx in self.pin_net:
                    continue
                # lead cells must be clear of foreign wires/pins
                if nx != start and self._descent_conflict(nx, net):
                    continue
                seen.add(nx); prev[nx] = cur; q.append(nx)
        return None

    def _tower_conflict(self, xz, net):
        """1x1 vertical tower base (a repeater facing WEST) at xz. A repeater
        couples only front/back (verified isolated on the sides), so:
          - reject if the cell itself is owned / is a foreign pin;
          - reject if a foreign wire is at the repeater's FRONT (west, x-1) or
            BACK/OUTPUT (east, x+1) — those DO short;
          - reject if a foreign pin is orthogonally adjacent.
        Side dust (z±1) and diagonals are harmless and allowed (this is what lets
        a tower stand in a congested channel)."""
        o = self.owner0.get(xz)
        if o is not None and o != net:
            return True
        if xz in self.pin_net and self.pin_net[xz] != net:
            return True
        # front/back (the west-facing repeater's conducting axis)
        for dx in (-1, 1):
            q = (xz[0]+dx, xz[1])
            oo = self.owner0.get(q)
            if oo is not None and oo != net:
                return True
        for dx, dz in _H:
            q = (xz[0]+dx, xz[1]+dz)
            po = self.pin_net.get(q)
            if po is not None and po != net:
                return True
        return False

    def _descent_conflict(self, xz, net):
        """A descent column touches y0..y4 at xz. Conflict if a foreign wire is
        at/adjacent on y0 OR on the cross plane."""
        if self._foreign_plane(xz, net, self.owner0):
            return True
        o0 = self.owner0.get(xz)
        if o0 is not None and o0 != net:
            return True
        if self._foreign_pin_adj(xz, net, xz):
            return True
        return False

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
        # A net counts as ROUTED only when EVERY sink is actually fed. The old
        # test (`not placements[n]`) passed any net with at least one placement,
        # so a net whose 2nd sink silently failed (its bridge returned None) was
        # still reported routed — that is why "26/29 routed" produced no signal
        # at the sinks. A sink is fed iff this net owns a wire/repeater adjacent
        # to (or at) the pin's west feed cell.
        failed = []
        for n in nets:
            if not placements[n]:
                failed.append(n); continue
            own = {(p[0], p[2]) for p in res.wires[n]} | \
                  {(pos[0], pos[2]) for (pos, _f) in res.repeaters[n]}
            bad = False
            for k in self.pl.net_sinks.get(n, []):
                kx, kz = k[0], k[2]
                # A gate input pin is a repeater[facing=west]: it reads ONLY the
                # cell to its WEST. Accepting any orthogonal neighbour counted
                # nets as routed while their signal actually arrived from the
                # north/south and could never enter the pin (n30 delivered 5 to
                # (93,0,-1) beside a pin that only reads (92,0,0)).
                if (kx - 1, kz) not in own:
                    bad = True; break
            if bad:
                failed.append(n)
        res.failed = failed
        return res

    def _insert_repeaters(self, net, pls, res):
        """Insert refresh repeaters on long y0 runs, oriented by the REAL signal
        flow.

        The previous version walked `placements` in list order and took the
        direction to the next listed cell. Placement order is not flow order (a
        net's sinks are routed one after another, so the list jumps around), which
        produced repeaters facing a direction the signal never comes from — e.g.
        n8 got repeater(facing=west) at (0,95) while its signal ran north from
        (0,96), so the repeater never conducted and the whole net was dead.

        Instead: BFS the net's own y0 cells outward from the source to build a
        parent->child tree (true flow), then every MAX_RUN hops replace that cell
        with a repeater facing the REVERSE of travel (a repeater reads the side it
        faces): +x -> west, -x -> east, +z -> north, -z -> south.
        """
        y0 = self.base_y
        # Preferred path: use the ORDERED per-sink paths recorded during routing.
        # Orientation then follows real travel, which the BFS-tree reconstruction
        # got wrong on multi-sink nets.
        # NOTE: an earlier attempt oriented repeaters from the ordered per-sink
        # paths (self.net_paths). That is the true travel direction, but the run
        # counter has to measure distance FROM THE SOURCE — a later sink's path
        # starts deep inside the existing tree, so restarting the count per path
        # placed refreshes too late and scored worse (18/24 vs 21/24). The BFS
        # tree below counts real depth from the source, which is what matters.
        cells = {(p[1], p[3]) for p in pls if p[0] == "dust" and p[2] == y0}
        if not cells:
            return
        src = self.pl.net_sources.get(net)
        if src is None:
            return
        start = (src[0], src[2])
        # BFS over the net's own y0 cells (the source pin itself may not be a cell)
        depth = {}
        q = deque()
        for dx, dz in _H:
            n0 = (start[0]+dx, start[1]+dz)
            if n0 in cells:
                depth[n0] = 1
                q.append((n0, (dx, dz)))
        # First pass: BFS to record each cell's arrival direction and parent.
        arrive = {}
        while q:
            cur, came = q.popleft()
            arrive[cur] = came
            for dx, dz in _H:
                nx = (cur[0]+dx, cur[1]+dz)
                if nx in cells and nx not in depth:
                    depth[nx] = depth[cur] + 1
                    q.append((nx, (dx, dz)))
        # Second pass: a repeater may only sit on a STRAIGHT run — it reads the
        # side it faces and drives the opposite one, so on a corner (arrival
        # direction != departure direction) its output points at empty space and
        # the net dies there. n8 broke exactly so: a repeater at (0,82) faced
        # south (arriving -z) while the path actually turned +x.
        children = {}
        for c, came in arrive.items():
            par = (c[0]-came[0], c[1]-came[1])
            children.setdefault(par, []).append(c)
        # Walk each root-to-leaf branch in flow order, carrying a distance
        # counter, and refresh at the FIRST straight cell at/after the threshold.
        # Requiring the repeater to land exactly on depth%MAX_RUN==0 was too
        # strict: if that cell happened to be a corner it was skipped and no
        # refresh happened at all, so a long branch decayed to 0 (n8's 205-cell
        # net died even though it was fully connected).
        def straight(c):
            came = arrive.get(c)
            kids = children.get(c, [])
            if came is None or len(kids) != 1:
                return None
            k = kids[0]
            if (k[0]-c[0], k[1]-c[1]) != came:
                return None
            return FLOW_FACING.get(came)

        roots = [c for c in arrive if depth.get(c) == 1]
        stack = [(rc, 0) for rc in roots]
        placed_rep = set()
        while stack:
            c, run = stack.pop()
            run += 1
            if run >= MAX_RUN - 1:
                f = straight(c)
                p3 = (c[0], y0, c[1])
                if f and p3 in res.wires[net] and p3 not in placed_rep:
                    res.repeaters[net].append((p3, f))
                    res.wires[net].discard(p3)
                    placed_rep.add(p3)
                    run = 0
            for k in children.get(c, []):
                stack.append((k, run))
