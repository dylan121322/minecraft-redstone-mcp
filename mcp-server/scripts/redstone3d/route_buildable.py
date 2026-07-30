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
            key = (len(res.failed), shorts)
            if verbose and (rnd < 3 or key < best_key):
                print(f"  round {rnd}: failed={len(res.failed)} shorts={shorts} "
                      f"order_head={order[:3]}", flush=True)
            if key < best_key:
                best_key = key; best_res = res
            if shorts == 0 and not res.failed:
                if verbose:
                    print(f"  converged at round {rnd}", flush=True)
                return res
            # failed nets get top priority next round; add their blockers' history
            for n in res.failed:
                if n not in priority:
                    priority.insert(0, n)
            self._bump_blocker_history(res)
        return best_res

    def _route_once(self, nets, soft: bool, verbose: bool = False) -> BuildResult:
        # fresh occupancy each round (rip-up everything)
        self.owner0 = {}; self.owner2 = {}; self.support1 = {}
        self.owner_cross = {}; self.net_cross_y = {}
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
                path = self._plane_bfs(tree, goal, net, soft=soft)
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
        spans = {n: xspan(n) for n in bridge_nets}
        def overlap(a, b):
            la, ra = spans[a]; lb, rb = spans[b]
            return not (ra < lb or rb < la)
        order = sorted(bridge_nets, key=lambda n: spans[n][1] - spans[n][0], reverse=True)
        color = {}
        for n in order:
            used = {color[m] for m in color if overlap(n, m)}
            c = 1
            while c in used:
                c += 1
            color[n] = c
        for net in bridge_nets:
            self.net_cross_y[net] = y0 + 4 * color[net]
        for net, goal in sorted(need_bridge, key=lambda ng: ng[0]):
            gadget = self._bridge(net, goal, placements, climbed)
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

    def _bump_blocker_history(self, res):
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
                            self.hist0[(xx, zz)] = self.hist0.get((xx, zz), 0.0) + 8.0

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
            sx, sz = s[0], s[2]
            # find a tower foothold via a 2-D y0 BFS from the source: the nearest
            # cell (any direction) whose repeater base is conflict-free, reached
            # by a clear y0 lead. Single-row +x search failed when the source row
            # was saturated (congested PI region). The lead follows the BFS path.
            foot = self._find_foothold(net, (sx, sz))
            if foot is None:
                return None
            (tx, tz), lead = foot
            for (lx, lz) in lead:
                p.append(("dust", lx, y0, lz))
                self.owner0[(lx, lz)] = net
            p.append(("rep", tx, y0, tz, "west"))
            self.owner0[(tx, tz)] = net
            yy = y0
            for _ in range(ncl):
                p.append(("block", tx, yy, tz))
                p.append(("torch", tx, yy+1, tz))
                yy += 2
            p.append(("dust", tx, cy_cross+1, tz))
            self.owner_cross.setdefault(cy_cross, {})[(tx, tz)] = net
            self.support1[(tx, tz)] = net
            climbed[net] = {(tx, tz)}
            sz = tz  # cross BFS starts from the tower's z

        # cross-plane BFS to the descent top at (gx-depth, gz), so the +x
        # staircase lands y0 at gx-1 (pin west feed), never covering the pin.
        cross_top = (gx - depth, gz)
        path = self._y2_bfs(set(climbed[net]), cross_top, net, cy_cross)
        if path is None:
            return None
        oc = self.owner_cross.setdefault(cy_cross, {})
        for (x, z) in path:
            if (x, z) in climbed[net]:
                continue
            p.append(("support", x, cy_cross, z)); p.append(("dust", x, cy_cross+1, z))
            oc[(x, z)] = net; self.support1[(x, z)] = net
            climbed[net].add((x, z))
        # DESCEND staircase from (gx-depth, cy_cross+1) to y0 at (gx-1). Check the
        # y0 landing cells for foreign conflict; abort (None) rather than short.
        for i in range(1, depth):
            if self._descent_conflict((gx - depth + i, gz), net):
                return None
        cx, cyy = gx - depth, cy_cross + 1
        while cyy > y0:
            cx += 1
            cyy -= 1
            if cyy > y0:
                p.append(("block", cx, cyy-1, gz)); p.append(("dust", cx, cyy, gz))
            else:
                p.append(("dust", cx, y0, gz))
            self.owner0[(cx, gz)] = net
            self.support1[(cx, gz)] = net
        return p

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
            if cur != start and not self._tower_conflict(cur, net):
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
                fed = any((kx + dx, kz + dz) in own
                          for dx, dz in ((-1, 0), (0, 0), (0, 1), (0, -1), (1, 0)))
                if not fed:
                    bad = True; break
            if bad:
                failed.append(n)
        res.failed = failed
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
