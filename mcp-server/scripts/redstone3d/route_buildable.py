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
S = "minecraft:stone"
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
    # REVIEW FINDING #4: standing torches must carry their NET so short-audits
    # can tell a tower's own rungs from a foreign net's conductors. Without this
    # every audit either over-counts (same-net torch vs wire) or under-counts
    # (two different nets' towers adjacent). BuildResult is used by
    # _materialize (placement order, per-net) so per-net torch lists fit.
    torch_nets: Dict[Pos, str] = field(default_factory=dict)
    # wall torches carry an explicit blockstate: the 2x2 down-tower rungs need a
    # specific facing, unlike the plain standing torches of the 1x1 up tower.
    wall_torches: List[Tuple[Pos, str]] = field(default_factory=list)
    wall_torch_nets: Dict[Pos, str] = field(default_factory=dict)
    # torch/wall_torch constructors are positional in _materialize; keep their
    # declared type as a plain field default so BuildResult(...) arity is stable.

    def total_wires(self) -> int:
        return sum(len(w) for w in self.wires.values())


class BuildableRouter:
    def __init__(self, placement: Placement, margin=10, global_vox: Dict[Pos, str] = None):
        self.pl = placement
        self.margin = margin
        self.global_vox = dict(global_vox or {})
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
        # TRUE 3-D occupancy of every conducting voxel (dust/repeater/torch) the
        # router places, keyed by (x, y, z). The per-plane tables above only track
        # (x, z) on one layer each, which cannot describe a vertical gadget: a
        # tower's intermediate rungs went unregistered, so neighbouring nets were
        # free to place wires right against them (that was the 4 shorts). Any new
        # three-dimensional gadget registers here and is checked here.
        self.owner3d: Dict[Pos, str] = {}
        # Pre-claim the global boxes' 3-D voxels: a local bridge tower rises to
        # y=9, and without this it would drive rungs straight through a global
        # delivery box's shell (measured: local wall_torches overwrote
        # n13:sink@93,21:box's shell stone). Claiming them here makes every
        # local _free3d/_descent_conflict check see the global geometry.
        # Only CONDUCTING global blocks are claimed: a delivery box's stone
        # SHELL does not conduct, and claiming it made local cross runs and
        # tower columns reject perfectly good sites next to the shell
        # (measured: n21's descent top at (249,2) sat beside a global shell at
        # (248,4,1) and every cross layer failed).
        for _pos, _gnet in self.global_vox.items():
            if _gnet.rsplit(":", 1)[-1] != "minecraft:stone":
                self.owner3d[_pos] = _gnet
        # negotiated-congestion history: per-cell penalty accumulated across
        # rip-up rounds. A cell that hosted a short in a prior round gets a
        # higher cost, so nets negotiate away from contested cells over rounds.
        self.hist0: Dict[XZ, float] = {}   # y=0 plane history cost
        self.histC: Dict[XZ, float] = {}   # cross (y4) plane history cost
        # cross-plane REFRESH REPEATER cells: a repeater block does not conduct
        # its input sideways, so a later sink's cross run starting on (or
        # passing through) a repeater cell reads 0 and the whole descent stays
        # dark (measured: n25's sink1 run started on sink2's (35,21) repeater
        # and its z=2 segment never lit).
        self.rep_cells: Set[XZ] = set()

    # ---------- helpers ----------
    def _foreign_plane(self, xz: XZ, net: str, owner: Dict[XZ, str]) -> bool:
        for dx, dz in _PLANE_SHELL:
            o = owner.get((xz[0]+dx, xz[1]+dz))
            if o is not None and o != net:
                return True
        return False

    # ---------- generic 3-D occupancy (works for any volumetric gadget) --------
    # Real redstone coupling, matching _count_shorts: same-layer 8-neighbourhood
    # plus the cells directly above and below. A full 26-cell shell also rejected
    # diagonal-across-layers pairs, which are actually isolated (verified in
    # CHANNEL_SPEC), and that over-strictness made the down tower unplaceable
    # almost everywhere (7 fits vs 48 rejections).
    _SHELL3D = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
                if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]

    def _claim3d(self, voxels, net: str) -> None:
        """Register conducting voxels as owned by `net`."""
        for v in voxels:
            self.owner3d[v] = net

    def _free3d(self, voxels, net: str) -> bool:
        """True if every voxel is unowned (or ours) AND no FOREIGN conducting
        voxel sits in its 26-neighbour shell. This is the general test a
        three-dimensional gadget needs; the flat per-layer checks miss vertical
        adjacency entirely."""
        vs = set(voxels)
        for v in vs:
            o = self.owner3d.get(v)
            if o is not None and o != net:
                return False
            for dx, dy, dz in self._SHELL3D:
                q = (v[0] + dx, v[1] + dy, v[2] + dz)
                if q in vs:
                    continue
                o = self.owner3d.get(q)
                if o is not None and o != net:
                    return False
        return True

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
        # Long nets FIRST: they need the cleanest corridors, and a short net
        # routed first claims the shared sink area, boxing the long one out
        # (measured: n25 span=32 routed before n5 span=46 and sealed n5's sink2
        # feed — its extend crossed z=18..21, n5's only landing rows).
        base_order = sorted(nets, key=lambda n: (len(self.pl.net_sinks[n]),
                                                 -span(n)))

        best_res = None; best_key = (1 << 30, 1 << 30)
        priority: List[str] = []          # nets to route first (grew from failures)
        for rnd in range(max_rounds):
            order = priority + [n for n in base_order if n not in priority]
            # bridge ordering mirrors the y0 ordering: last round's failures get
            # to claim contested descent areas FIRST this round.
            self._bridge_priority = priority
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
        self.net_paths = {}; self.owner3d = {}
        placements: Dict[str, List[tuple]] = {n: [] for n in nets}
        need_bridge: List[Tuple[str, XZ]] = []
        y0 = self.base_y
        for net in nets:
            s = self.pl.net_sources[net]
            src_xz = (s[0], s[2])
            self.owner0.setdefault(src_xz, net)
            tree: Set[XZ] = {src_xz}
            first = True
            for k in sorted(self.pl.net_sinks[net],
                            key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2]),
                            reverse=True):
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
                    self.owner3d[(x, y0, z)] = net
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
        # priority nets (last round's failures) bridge FIRST, mirroring the y0
        # order: otherwise a net alphabetically earlier always claimed the
        # contested descent area first and the failed net could never fit.
        priority = getattr(self, '_bridge_priority', None)
        bridge_order = sorted(need_bridge,
                              key=lambda ng: (ng[0] not in (priority or ()),
                                              ng[0]))
        for net, goal in bridge_order:
            # try the lowest cross layer first, stepping up (+4 Y each time, so
            # the torch count stays even => non-inverting) only when this layer
            # is genuinely blocked. Keeps hops shallow and short.
            gadget = None
            saved = self.net_cross_y.get(net, y0 + 4)
            for attempt in range(6):
                # ONCE this net's climb tower is up (an earlier sink succeeded),
                # the layer is LOCKED: a later sink retrying on a higher layer
                # would lay its cross on cy+1 while the tower's top stays at the
                # old cy — the run flies into empty air and the descent never
                # lights (measured: n6's sink2 cross at y=9 vs its tower at
                # cy=4). Failed later sinks fail the WHOLE net (best-res
                # comparison drops it) instead of re-layering.
                if attempt > 0 and net in climbed:
                    break
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
        # Global trunk boxes sit on THEIR plane (base+5+4k), which a local
        # cross layer can share numerically. A local wire placed one cell beside
        # a trunk wire is a real MC short-adjacency (measured: n3's trunk at
        # (9,21,20) read 9 with its source cut, driven by local wires at
        # (9,21,19)/(9,21,21)); ON the trunk cell itself it overwrites it
        # (measured: a local cross repeater landed on n13's trunk leg at
        # (78,9,42)). Check the cell itself and the 8-neighbourhood.
        # Only CONDUCTING global blocks matter: a global box's stone SHELL does
        # not conduct, and rejecting it boxed whole sinks out (measured: n21's
        # descent top at (249,2) sat beside a global shell at (248,4,1) and the
        # strict check left it unroutable at every cross layer).
        def _conductive(gv):
            # values arrive as "g:<blockstate>" from the global-first router
            return gv is not None and gv.rsplit(":", 1)[-1] != "minecraft:stone"
        gv = self.global_vox.get((xz[0], cy, xz[1]))
        if _conductive(gv):
            return False
        for dx, dz in _PLANE_SHELL:
            q = (xz[0] + dx, cy, xz[1] + dz)
            if _conductive(self.global_vox.get(q)):
                return False
        # A cross wire at cy is dust at cy+1. ANOTHER net's DESCEND rung can sit
        # on the same height from a higher cross layer (cy=8 descends through
        # y=5 beside a cy=4 cross wire) — measured on Control: n3's descend rung
        # (17,5,71) sat next to n4's cross (17,5,72) and shorted, because each
        # check only saw its own layer. owner3d sees every conducting voxel, so
        # check the dust height's 8-neighbourhood there.
        dy = cy + 1
        o = self.owner3d.get((xz[0], dy, xz[1]))
        if o is not None and o != net:
            return False
        for dx, dz in _PLANE_SHELL:
            o = self.owner3d.get((xz[0] + dx, dy, xz[1] + dz))
            if o is not None and o != net:
                return False
            # ANY torch cell (even this net's) in the 8-neighbourhood: a lit
            # torch couples diagonally in MCHPRS and a tower's intermediate
            # torch is lit exactly when the net is OFF (measured: n5's
            # 4-torch tower torch5 lit at drive0, driving the mainline at 15).
            if o is not None and str(o).endswith(":torch"):
                return False
        # A refresh REPEATER cell (even this net's) does not conduct sideways:
        # a wire one cell beside it reads 0 and the run stays dark (measured:
        # n25's z=2 segment started beside sink2's (35,21) repeater and never
        # lit). Reject the repeater's 8-neighbourhood as well as the cell.
        if xz in self.rep_cells:
            return False
        for dx, dz in _PLANE_SHELL:
            if (xz[0] + dx, xz[1] + dz) in self.rep_cells:
                return False
        return True

    def _y2_bfs(self, sources, goal, net, cy):
        # Weighted BFS: a z-move costs 1, an x-move costs X_PEN. The unweighted
        # BFS found whichever path came first, and on this layout that was an L
        # with a LONG x-vertical leg (n18's cross ran east along z=22 to x=67,
        # then south along x=67 to z=57 — and x=67 is EVERY sink's west feed
        # column, so the leg occupied n24's feed (67,40) and blocked its
        # down-tower at every height). Preferring z-moves keeps the long leg in
        # the SOURCE's column, leaving only a short x-run at the goal.
        import heapq
        X_PEN = 6.0
        # Sources that are refresh REPEATERS carry no sideways signal — a run
        # starting on one reads 0 (measured: n25). Start from the other cells.
        sources = {s for s in sources if s not in self.rep_cells}
        if not sources:
            return None
        dist = {c: 0.0 for c in sources}
        prev: Dict[XZ, XZ] = {}
        pq = [(0.0, c) for c in sources]
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
                # The GOAL cell is checked too: it is the descent top, and a
                # foreign cross wire diagonally beside it shorts the sink
                # (measured: n25's cross at (35,5,18) sat diagonal to n5's
                # descent top (36,5,19) — the goal exemption let it through).
                if not self._y2_free(nx, net, cy):
                    continue
                # A refresh REPEATER cell does not conduct sideways — a path
                # through it reads 0 and the descent dies (measured: n25).
                if nx in self.rep_cells:
                    continue
                nd = d + (X_PEN if dx else 1.0)
                if nd < dist.get(nx, float("inf")):
                    dist[nx] = nd; prev[nx] = cur
                    heapq.heappush(pq, (nd, nx))
        return None

    def _bridge(self, net, goal_xz, placements, climbed):
        """Transactional wrapper: a failed attempt must not leave occupancy
        behind, or the next attempt (and the next round) sees ghost towers and
        keeps failing (measured: n5's climb tower at (15,0) survived a failed
        attempt and its rung torch sat on the sink stair's seat).

        A second attempt with _force_new_tower is made when the tree-based
        attempt fails: some sinks CANNOT be reached from the existing tower
        (its cross run's supports would sit on their staircase seats — n6's
        sink2), and only a dedicated tower at their own extension end works.
        """
        snap0 = dict(self.owner0)
        snap3 = dict(self.owner3d)
        snap1 = dict(self.support1)
        snap_oc = {k: dict(v) for k, v in self.owner_cross.items()}
        snap_rep = set(self.rep_cells)
        snap_climbed = dict(climbed)
        res = self._bridge_inner(net, goal_xz, placements, climbed)
        if res is None:
            self.owner0 = snap0
            self.owner3d = snap3
            self.support1 = snap1
            self.owner_cross = snap_oc
            self.rep_cells = snap_rep
            # Restore `climbed` wholesale so a later sink's failed attempt cannot
            # wipe the tower an EARLIER sink of the same net already built (they
            # share the dict). A/B-measured on alu1/Control/Mux2to1: identical
            # results either way, because the outer retry loop's own
            # `climbed.pop(net)` already covers the cases these modules hit. Kept
            # as defence for multi-sink nets that the current set does not
            # exercise — NOT claimed as a measured win.
            climbed.clear(); climbed.update(snap_climbed)
        return res

    def _bridge_inner(self, net, goal_xz, placements, climbed):
        """Route a bridged sink on the CROSS plane (y=4).

        Climb ONCE per net via
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

        tx = tz = None        # climb tower foot (may be unused on later sinks)
        lead = []
        s = self.pl.net_sources[net]
        # EVERY sink gets its own tower ONLY when the existing tree cannot
        # reach it: a long shared cross lays its SUPPORT blocks over the later
        # sink's staircase seats (measured: n6's sink2), but an UNNEEDED second
        # tower's extension seals the neighbour's corridors (measured: n25's
        # sink2 tower at (40,22) + its (40,17..21) extension boxed out n5's
        # sink2, whose every staircase row ran beside n25's wire). The outer
        # _bridge retries with _force_new_tower when the tree-based attempt
        # fails.
        # MINIMAL HOP: start the climb from the point of the net's ALREADY
        # ROUTED y0 tree that is closest to this sink, not from the source.
        # Climbing at the source made the signal travel the whole way on the
        # cross plane (n8: 133 cross cells for an 8-cell obstacle, n13: 216),
        # which wastes space and multiplies the adjacency surface. The real
        # blockage is only a few cells wide, so we hop just over it.
        #
        # EVERY sink gets its own tower when the extension reaches it: a long
        # cross run shared with an earlier sink lays its SUPPORT blocks over the
        # later sink's staircase seats and the stair never conducts (measured:
        # n6's sink2 cross from sink1's tower at (40,0) laid supports on
        # (38,4,38), sealing sink2's stair). A per-sink tower keeps the cross
        # short enough to miss the stair area.
        ext = self._extend_toward(net, placements, goal_xz)
        anchor = ext[0] if ext else None
        adir = ext[1] if ext else None
        sx, sz = anchor if anchor else (s[0], s[2])
        # When the extension reached the goal's neighbourhood, put the climb
        # tower ONE CELL BEYOND the extension's end, driven by a repeater at
        # the end itself: the repeater reads the incoming cell (its facing
        # side) and outputs to the foot. The old _find_foothold BFS could
        # pick a foot that was PERPENDICULAR to the extension, forcing the
        # repeater onto a corner where its output fired into empty air
        # (measured: n5's climb at (1,24), n20's at (214,2) — both dark).
        # ONE tower per net: a later sink may EXTEND its tree (a second tower at
        # the new extension's end would sit on a DIFFERENT cross layer — its
        # climb torch count is computed from the net's fixed cy, so the run
        # flies into empty air and the descent stays dark; measured: n6's sink2
        # tower at (41,39) with the sink1 tower at (0,40)).
        if net in climbed:
            anchor = adir = None
        if anchor and adir:
            tx, tz = sx + adir[0], sz + adir[1]
            if (tx, tz) in self.cell_xz or (tx, tz) in self.pin_net or \
                    self._tower_conflict((tx, tz), net) or \
                    not self._in_box((tx, tz)):
                tx = tz = None
        if tx is None and net not in climbed:
            foot = self._find_foothold(net, (sx, sz))
            if foot is None:
                return None
            (tx, tz), lead = foot
            for (lx, lz) in lead:
                p.append(("dust", lx, y0, lz))
                self.owner0[(lx, lz)] = net
        if tx is not None and not self._tower_torch_ok((tx, tz), net):
            tx = tz = None
        if tx is not None:
            if lead:
                prev_cell = lead[-1]
                p = [q for q in p if not (q[0] == "dust" and q[1] == prev_cell[0]
                                          and q[3] == prev_cell[1])]
                p.append(("rep", prev_cell[0], y0, prev_cell[1],
                          FLOW_FACING.get((tx - prev_cell[0], tz - prev_cell[1]), "west")))
                self.owner0[prev_cell] = net
            else:
                p.append(("rep", sx, y0, sz, FLOW_FACING.get(adir, "west")))
                self.owner0[(sx, sz)] = net
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
                self.owner3d[(tx, yy, tz)] = net
                # torch 格标记 :torch — 它的亮/灭在 drive0 恒亮时会耦合
                # 同 net 的其他路径（measured: n5 的 4-torch 塔 torch5 对角
                # 耦合主线 (25,5,19)），cross/descent 必须避开
                self.owner3d[(tx, yy+1, tz)] = f"{net}:torch"
                yy += 2
            p.append(("block", tx, cy_cross, tz))       # top block
            p.append(("dust", tx, cy_cross+1, tz))      # cross-plane dust
            self.owner3d[(tx, cy_cross, tz)] = net
            self.owner3d[(tx, cy_cross+1, tz)] = net
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
        # FIRST CHOICE: the 2x2 DOWN TOWER (via_gadget.down_tower_cells_dir,
        # verified in test_tower_bidir / test_down_dirs — non-inverting, full
        # strength at the bottom, four usable rotations). Its footprint does not
        # grow with the drop, unlike a staircase, so it fits where a corridor
        # cannot. Occupancy is registered in the general 3-D table so neighbouring
        # nets keep clear of the rungs. If no rotation fits we fall back to the
        # staircase search below, which keeps every net that already routed.
        # The tower is tried as a FALLBACK, after the staircase search below —
        # measured: giving it priority made things worse (8 unrouted vs 5). Its
        # footprint is small in Y but claims four (x,z) columns around the feed
        # cell, whereas a staircase claims a single row; in this placement a free
        # row turns out easier to find than a free 2x2. Keeping the tower as the
        # fallback is monotone: every net the staircase could route still routes,
        # and nets it cannot may still get a tower.
        dt = None
        if dt is not None:
            rot, y_from, pre, cells, foot, cond = dt
            path = self._y2_bfs(set(climbed[net]), (gx - 1, gz), net, cy_cross)
            if path is not None:
                self._lay_cross(net, path, cy_cross, climbed, p)
                p += pre
                for (x, y, z, b) in cells:
                    if b == "minecraft:redstone_wire":
                        p.append(("dust", x, y, z))
                    elif "torch" in b:
                        p.append(("wtorch", x, y, z, b))
                    else:
                        p.append(("block", x, y, z))
                p.append(("dust", gx, y0, gz))
                self._claim3d(cond, net)
                for c in foot:
                    self.owner0.setdefault(c, net)
                    self.support1[c] = net
                self.owner0[(gx - 1, gz)] = net
                return p

        # Deep descents (>11 steps) take the DOWN TOWER first: a staircase that
        # deep decays to 0 before the bottom (dust loses 1 per step; measured:
        # n7's cy=12 stair delivered 0/2), while the tower regenerates at every
        # rung and is verified (test_tower_bidir). Only fall back to the
        # staircase when no tower rotation fits.
        #
        if depth > 11:
            dt = self._pick_down_tower(net, (gx, gz), cy_cross)
            if dt is not None:
                rot, y_from, pre, dcells, foot, cond = dt
                if net not in climbed:
                    return None
                path = self._y2_bfs(set(climbed[net]), (gx - 2, gz), net, cy_cross)
                if path is not None:
                    self._lay_cross(net, path, cy_cross, climbed, p)
                    p += pre
                    for (x, y, z, b) in dcells:
                        if b == "minecraft:redstone_wire":
                            p.append(("dust", x, y, z))
                        elif "torch" in b:
                            p.append(("wtorch", x, y, z, b))
                        else:
                            p.append(("block", x, y, z))
                    p.append(("dust", gx, y0, gz))
                    self._claim3d(cond, net)
                    for c in foot:
                        self.owner0.setdefault(c, net)
                        self.support1[c] = net
                    self.owner0[(gx - 1, gz)] = net
                    return p
        # Prefer the pin's OWN row (dz=0) only when it is clear; otherwise
        # prefer LARGER offsets: a corridor on an adjacent row (dz=±1/±2) can
        # sit inside a neighbour's feed 8-neighbourhood and cross-couple the
        # sinks (measured: n25's zz=21 stair + jog left n5's feed (41,19)
        # diagonal to n25's (42,20) wire — a frozen 10). Offsets >= 3 keep the
        # two nets' y0 runs apart.
        # Own row (dz=0) FIRST when it is clean: the stair's last step lands on
        # the feed and no jog is needed (measured: n8's sink1 stair on z=52 —
        # an offset row — crossed its own cross run's support blocks and died;
        # its own row z=55 is clear). Offset rows are only chosen when the own
        # row is blocked.
        cand = [("W", dz) for dz in (0, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7,
                                     8, -8, 1, -1, 2, -2)]
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
            if any(self._descent_conflict(c, net, cy_cross) for c in cells):
                continue
            # THIS net's climb tower foot is already on the plane: a staircase
            # landing on it overwrites the tower's block0 and the climb never
            # fires (measured: n6's sink1 descent zz=0 landed on the climb foot
            # at (40,0) — _descent_conflict only rejects FOREIGN owners).
            if tx is not None and any(c == (tx, tz) for c in cells):
                continue
            # The stair's FIRST step reads the cross cell directly above it
            # ((cells[0], cy_cross+1)): if that cell is a refresh REPEATER, the
            # block does not conduct downward and the whole stair stays dark
            # (measured: n6's sink2 stair at (37,4,38) sat under the cross
            # repeater at (37,5,38) and read 0).
            if (cells[0][0], zz) in self.rep_cells:
                continue
            # STAIRCASE SEATS must be AIR: each diagonal step (x,y)->(x+1,y-1)
            # only conducts when the cell directly above the landing is empty,
            # and a block or torch there kills the step (measured: n5's stair
            # at (15,2,0) sat dark because a climb-tower torch occupied its
            # seat (15,3,0)).
            seats = [(gx - depth + i, cy_cross + 2 - i, zz)
                     for i in range(1, depth + 1)]
            if any(self._seat_blocked(s, net) for s in seats):
                continue
            # when the corridor runs on an offset row (zz != gz) the landing is
            # not yet beside the pin: add a short y0 jog along z from the landing
            # to the pin's feed cell, and require that jog to be clear too.
            jog = []
            if zz != gz:
                step = 1 if gz > zz else -1
                # jog along the FEED column (x = gx): the stair lands at
                # (gx-1, zz) and the jog must END at the pin's feed cell
                # (gx, gz) — jogging on the landing column (gx-1) stopped one
                # cell short and the feed never lit (measured: n7's sink2 stair
                # on z=18 jogged to (91,19) while the feed sat at (92,19)).
                for t in range(zz, gz + step, step):
                    jog.append((gx, t))
                if any(c in self.cell_xz or c in self.pin_net for c in jog):
                    continue
                if any(self._descent_conflict(c, net, cy_cross) for c in jog):
                    continue
            else:
                # zz == gz: the stair's last step lands ON the feed cell — its
                # 8-neighbourhood must be clear (a foreign wire diagonally
                # beside it couples; measured: n5's feed (41,19) sat diagonal
                # to n25's extension (40,21) and read a frozen 10).
                if self._descent_conflict((gx, gz), net, cy_cross):
                    continue
                # The stair's last step (gx-1, y0+1) needs its support block at
                # (gx-1, y0) — if THIS net's own extend wire sits there, the
                # wire (emitted after supports) replaces the block, the step
                # floats and the feed stays dark (measured: n25's sink2 — the
                # extend path to its tower foot ran through (40,0,21), directly
                # under the stair's final step). Reject the own row; the offset
                # corridors avoid the extend path.
                if self.owner0.get((gx - 1, gz)) == net:
                    continue
                # The stair bottom sits at (gx-1, y0); the FEED is (gx, y0).
                # A 1-cell horizontal jog connects them (a vertical dust pair
                # under the last step does not conduct — measured: n25's sink2
                # feed stayed dark).
                jog = [(gx, gz)]
            chosen = (side, zz, cells, jog)
            break
        if chosen is None:
            # No staircase corridor fits — fall back to the 2x2 DOWN TOWER, whose
            # footprint does not grow with the drop (via_gadget, verified in
            # test_tower_bidir / test_down_dirs). This only ADDS reach.
            dt = self._pick_down_tower(net, (gx, gz), cy_cross)
            if dt is None:
                return None
            rot, y_from, pre, dcells, foot, cond = dt
            if net not in climbed:
                # the tower was rejected and the staircase found nothing —
                # nothing to climb from (mirrors the deep-descent branch at
                # line 812; without this guard the set() below raises KeyError
                # and crashes the whole route — found by review, Control/n3).
                return None
            path = self._y2_bfs(set(climbed[net]), (gx - 2, gz), net, cy_cross)
            if path is None:
                return None
            self._lay_cross(net, path, cy_cross, climbed, p)
            p += pre
            for (x, y, z, b) in dcells:
                if b == "minecraft:redstone_wire":
                    p.append(("dust", x, y, z))
                elif "torch" in b:
                    p.append(("wtorch", x, y, z, b))
                else:
                    p.append(("block", x, y, z))
            p.append(("dust", gx, y0, gz))
            self._claim3d(cond, net)
            for c in foot:
                self.owner0.setdefault(c, net)
                self.support1[c] = net
            self.owner0[(gx, gz)] = net
            return p
        side, zz, cells, jog = chosen
        if net not in climbed:
            # the tower was rejected (e.g. torch 8-neighbourhood conflict) —
            # nothing to climb from
            return None
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
            # Register the conducting voxel in the 3-D table. This is the
            # staircase branch's INLINE cross lay (it does not call _lay_cross),
            # and without this the cross wires were invisible to _descent_conflict
            # — another net's descent then placed its rungs right beside them
            # (measured: n7's descent at (87,5,19) shorted n30's cross at
            # (87,5,18)/(87,5,20) because owner3d was empty).
            self.owner3d[(x, cy_cross+1, z)] = net
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
                self.rep_cells.add((rc[0], rc[1]))

        # emit the staircase along the chosen corridor
        cyy = cy_cross + 1
        for (cx, cz) in cells:
            cyy -= 1
            if cyy > y0:
                p.append(("block", cx, cyy-1, cz)); p.append(("dust", cx, cyy, cz))
                self.owner3d[(cx, cyy, cz)] = net   # intermediate rung is conducting
                self.owner3d[(cx, cyy-1, cz)] = net  # rung support block too
            else:
                p.append(("dust", cx, y0, cz))
            # Register the STAIRCASE SEAT (the cell above this landing) as
            # owned air: a later tower must not place a rung there, or the
            # diagonal step seals (measured: n5's sink-2 climb tower torch sat
            # on sink-1's stair seat and killed it). The ":seat" marker lets
            # _tower3d_conflict reject ONLY these cells — a tower column may
            # legitimately rise beside a foreign net's cross run.
            self.owner3d[(cx, cyy + 1, cz)] = f"{net}:seat"
            # Register the column in the SAME cross layer too: another net's
            # _y2_bfs (its cross-plane BFS) checks only owner_cross, so a descent
            # staircase here was invisible to it and it laid its own cross run
            # right beside the rungs (measured: n30's cross (87,5,18/20) shorted
            # n7's descent rung at (87,5,19)).
            oc = self.owner_cross.setdefault(cy_cross, {})
            oc[(cx, cz)] = net
            self.owner0[(cx, cz)] = net
            self.support1[(cx, cz)] = net
        # y0 jog from the landing row to the pin's feed cell (offset corridors)
        for (jx, jz) in jog:
            p.append(("dust", jx, y0, jz))
            self.owner0[(jx, jz)] = net
        return p

    def _lay_cross(self, net, path, cy_cross, climbed, p):
        """Emit a cross-plane run with refresh repeaters, registering both the
        per-layer and the 3-D occupancy. Shared by the down-tower delivery and the
        staircase delivery so both stay consistent."""
        oc = self.owner_cross.setdefault(cy_cross, {})
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
                if f and came == leave:
                    p.append(("support", x, cy_cross, z))
                    p.append(("rep", x, cy_cross+1, z, f))
                    self.rep_cells.add((x, z))
                    self.owner3d[(x, cy_cross, z)] = net
                    placed_rep = True
                    run = 0
            if not placed_rep:
                p.append(("support", x, cy_cross, z))
                p.append(("dust", x, cy_cross+1, z))
            # register the CONDUCTING voxel (the dust/repeater at cy_cross+1) in
            # the 3-D table: _descent_conflict now checks whole columns against
            # owner3d, so a cross run that another net's descent crosses must be
            # visible there (measured: n30's cross run at (87,5,18/20) shorted
            # n7's descent at (87,5,19) because the cross voxels were only in
            # owner_cross, which the descent check never read).
            self.owner3d[(x, cy_cross+1, z)] = net
            # register the SUPPORT layer too: a staircase seat check reads
            # owner3d, and an unregistered support let a descent stair land on
            # the cross run's support block (measured: n6's sink2 stair at
            # (38,3,38) sat on the (38,4,38) cross support and died).
            self.owner3d[(x, cy_cross, z)] = net
            oc[(x, z)] = net
            self.support1[(x, z)] = net
            climbed[net].add((x, z))

    def _pick_down_tower(self, net, pin_xz, cy_cross):
        """Choose a 2x2 DOWN-tower rotation that fits in the pin's west feed
        column. Pure selection + legality (no emission), so it stays reusable:
        the voxels come from via_gadget and legality is the generic 3-D check,
        nothing module-specific. Returns
        (rot, y_from, pre, cells, foot, conducting_voxels) or None."""
        from via_gadget import down_tower_cells_dir
        y0 = self.base_y
        gx, gz = pin_xz
        feed = (gx - 1, gz)
        if feed in self.cell_xz or feed in self.pin_net:
            return None
        # Input chain (all verified in MCHPRS): the cross run's LAST dust ends
        # one column west of the feed at (feed_x-1, cy_cross+1); a STAIR step
        # down (the (feed_x, cy_cross+1) seat stays air) reaches the in dust at
        # (feed_x, cy_cross); that dust weakly powers the A support directly
        # below it, which strongly powers the A column top. A vertical dust pair
        # or a 3-deep block chain both die in MCHPRS (measured), so the stair is
        # the only way across the layer gap.
        y_from = cy_cross
        pre = [("dust", feed[0], cy_cross, feed[1])]
        if y_from <= y0:
            return None
        # Try all 8 rotations. The original 4 always extended the tower's foot
        # to the EAST (arm/side x = +1), so the foot column at x=gx landed on the
        # gate body whose pin sits at (gx,gz) — every sink at the west edge of a
        # gate failed (measured: n7/n8/n21 all FOOT_OC at (gx,gz)). The 4 -x
        # rotations extend the foot WEST instead, keeping it on open ground.
        # STAIR-INPUT rotations FIRST: with the in dust at (feed_x, cy_cross),
        # only arm=(0,±1) keeps the torch column off both the feed cell and the
        # cross run's end (measured: arm=(0,1) side=(-1,0) reads feed 0/14,
        # every other rotation leaks 14/15 at drive=0 or never turns on).
        for arm, side in (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
                          ((-1, 0), (0, 1)), ((-1, 0), (0, -1)),
                          ((0, 1), (1, 0)), ((1, 0), (0, 1)),
                          ((1, 0), (0, -1)), ((0, -1), (1, 0))):
            cells, foot = down_tower_cells_dir(feed[0], feed[1], y_from, y0,
                                               side=side, arm=arm)
            if any(c in self.cell_xz or c in self.pin_net for c in foot):
                continue
            DUST = "minecraft:redstone_wire"
            cond = [(x, y, z) for (x, y, z, b) in cells
                    if b == DUST or "torch" in b]
            cond.append((feed[0], y0, feed[1]))
            cond += [(q[1], q[2], q[3]) for q in pre if q[0] == "dust"]
            if not self._free3d(cond, net):
                continue
            # The tower's GROUND voxels sit on the y0 plane, where extension
            # wires are tracked in owner0 but NOT owner3d (extensions register
            # only owner0). A tower A column landing on another net's extension
            # wire overwrites it and shorts both nets (measured: n5's tower A
            # (40,19) landed on n25's extension (40,19) — 4 shorts).
            if any(c[1] == y0 and self.owner0.get((c[0], c[2])) not in (None, net)
                   for c in cond):
                continue
            # The FEED wire one cell east of the tower couples to a foreign wire
            # in its 8-neighbourhood too (measured: n5's feed (41,19) sat
            # diagonal to n25's extension (40,20) and read a frozen 10 with the
            # source cut).
            if any(self.owner0.get((feed[0]+_dx, feed[1]+_dz)) not in (None, net)
                   for _dx, _dz in _PLANE_SHELL):
                continue
            if not self._y2_free(feed, net, cy_cross):
                continue
            return (arm, side), y_from, pre, cells, foot, cond
        return None

    def _seat_blocked(self, seat, net):
        """True if a staircase seat cell (directly above a landing dust) is
        occupied by anything conducting — a block, dust, torch or repeater. The
        seat itself is never part of the stair, but a foreign block there seals
        the diagonal step in MCHPRS (measured)."""
        if seat in self.cell_xz or seat in self.pin_net:
            return True
        if seat in self.owner3d:
            return True
        return False

    def _tower_torch_ok(self, xz, net):
        """True if a 1x1 climb tower's torch cells have no foreign conducting
        voxel in their 8-neighbourhood. A tower's INTERMEDIATE torch is lit
        exactly when the net is OFF, and a lit torch couples diagonally in
        MCHPRS (measured: n25's 4-torch tower torch5 at (26,5,20) lit at
        drive0, driving n5's mainline (25,5,19) at 15)."""
        yb = self.base_y
        top = self.net_cross_y.get(net, yb + 4)
        for yy in range(yb + 1, top + 1, 2):
            for dx, dz in _PLANE_SHELL:
                o = self.owner3d.get((xz[0] + dx, yy, xz[1] + dz))
                if o is not None and o != net:
                    return False
        return True

    def _tower3d_conflict(self, xz, net):
        """The 1x1 climb tower occupies the WHOLE column (tx, y0..cy_cross+1,
        tz) with alternating blocks and standing torches. Any of those voxels
        already claimed in owner3d — even by THIS net, e.g. a staircase seat
        registered by an earlier sink — seals the tower (measured: n5's sink-2
        climb tower rung sat on sink-1's stair seat (15,3,0) and the stair
        never conducted)."""
        yb = self.base_y
        top = self.net_cross_y.get(net, yb + 4) + 1
        # Only STAIRCASE SEATS block the tower column: any block at all in a
        # seat seals a stair, so even this net's own seat kills the tower.
        # Ordinary foreign voxels (cross runs, other towers) are allowed —
        # rejecting them made the routing oscillate (measured: n8's climb
        # column collided with n7's cross at (0,5,*) one round and routed fine
        # the next, so rounds flipped between them forever).
        return any(str(self.owner3d.get((xz[0], yy, xz[1]))).endswith(":seat")
                   for yy in range(yb, top + 1))


    def _extend_toward(self, net, placements, goal_xz):
        """Push the net's y0 route as CLOSE to goal_xz as the plane allows, lay
        that dust, and return the closest cell reached whose BEYOND-cell is a
        legal climb-tower foot. The bridge then only has to hop the residual
        gap (measured: n8's real blockage is 8 cells wide, while climbing at
        the source made it fly 133 cells on the cross plane).
        Returns (best, adir, path) or (best, None, None)."""
        y0 = self.base_y
        tree = {(p[1], p[3]) for p in placements.get(net, [])
                if p[0] == "dust" and p[2] == y0}
        s = self.pl.net_sources[net]
        tree.add((s[0], s[2]))
        gx, gz = goal_xz
        # The BFS is confined to a box around the goal (GOAL_BOX cells each way).
        # Without this the extension path from a distant source wound through the
        # whole gate grid and laid hundreds of y0 cells (measured: n14's src
        # (104,20) -> goal (119,2) filled x=92..160, z=-2..22 and boxed n17's
        # source into an island). The bridge only needs to hop the LOCAL obstacle,
        # so laying dust any farther than the goal's neighbourhood is both wasted
        # and harmful.
        GOAL_BOX = 10
        def nbh(c):
            return abs(c[0]-gx) <= GOAL_BOX and abs(c[1]-gz) <= GOAL_BOX

        def tower_ok(p, dirv):
            """A 1x1 climb tower's FOOT can stand at p+dirv (the cell the
            extension's repeater outputs to). The foot must be off gate bodies,
            off the goal's feed cell (the descent must land there), and free of
            tower conflicts — otherwise the bridge falls back to _find_foothold,
            whose L-shaped leads put the drive repeater on a corner where it
            reads empty air (measured: n20's extension ended at (216,2) with
            its foot (217,2) on a gate body; n6's foot (41,0) collided with
            the feed cell)."""
            q = (p[0]+dirv[0], p[1]+dirv[1])
            if q == goal_xz:
                return False
            if q in self.cell_xz or q in self.pin_net:
                return False
            if self._tower_conflict(q, net):
                return False
            if self._tower3d_conflict(q, net):
                return False
            return True

        prev = {}; seen = set(tree); q = deque(tree)
        # best = closest cell whose BEYOND-cell is a legal tower foot
        best = None; best_d = None
        for c in tree:
            d = abs(c[0]-gx) + abs(c[1]-gz)
            if best is None or d < best_d:
                best_d = d; best = c
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
                if nbh(nx):
                    d = abs(nx[0]-gx) + abs(nx[1]-gz)
                    # the extension must END on a straight stretch whose next
                    # cell can host the climb tower's foot
                    if d < best_d and tower_ok(nx, (dx, dz)):
                        best_d = d; best = nx
        if best in tree:
            return (best, None, None)

        # lay the dust along the path to `best`, ONLY inside the goal's box —
        # the source-side portion of the path is not ours to claim. EXCEPT when
        # the net has NO y0 tree at all (its flat BFS failed every sink, so it
        # has no source-side wiring): then the whole src->best path must be laid
        # or the climb tower stands on a wire that never reaches the source
        # (measured: n22's tower at (244,21) had no input, the cross plane never
        # lit and the sink sat at a frozen 15).
        have_y0 = any(p[0] == "dust" and p[2] == y0
                      for p in placements.get(net, ()))
        path = [best]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        for c in path:
            if c in tree or c in self.pin_net:
                continue
            if not have_y0 or nbh(c):
                placements[net].append(("dust", c[0], y0, c[1]))
                self.owner0[c] = net
        # direction the path is travelling when it reaches best — the climb
        # tower sits one cell BEYOND best in this direction, driven by a
        # repeater AT best that reads the incoming cell and outputs to the foot
        adir = None
        if len(path) >= 2:
            a, b = path[-2], path[-1]
            adir = (b[0] - a[0], b[1] - a[1])
        return (best, adir, path)

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
            # The foothold must be COLLINEAR with the start (same x or same z):
            # the driving repeater sits on the lead's last cell, reading the
            # direction it came from and outputting the OPPOSITE way — so it can
            # only drive a tower that lies straight ahead. An L-shaped lead put
            # the repeater on the corner, where its output fired into empty air
            # and the tower stayed dark (measured: n5's climb at (1,24) with the
            # repeater at (1,23) outputting east, tower foot south).
            if cur != start and hops >= 2 and \
                    (cur[0] == start[0] or cur[1] == start[1]) and \
                    not self._tower_conflict(cur, net) and \
                    not self._tower3d_conflict(cur, net) and \
                    self._tower_torch_ok(cur, net):
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

    def _descent_conflict(self, xz, net, y_top: int = None):
        """A descent column touches every layer from y0 up to the net's cross
        plane at xz. Conflict if a foreign wire is at/adjacent on y0 OR on any
        intermediate layer. The intermediate layers were the gap: two nets on
        DIFFERENT cross layers (y4 vs y24) descended through the same xz and
        their staircases brushed at y=5 with no ownership check (measured: n7's
        descend at (87,5,19) shorted n30's descend at (87,5,18)/(87,5,20)).
        owner3d holds every conducting voxel placed so far, so check the whole
        column against it."""
        if self._foreign_plane(xz, net, self.owner0):
            return True
        o0 = self.owner0.get(xz)
        if o0 is not None and o0 != net:
            return True
        if self._foreign_pin_adj(xz, net, xz):
            return True
        if y_top is not None:
            for y in range(self.base_y + 1, y_top + 1):
                o = self.owner3d.get((xz[0], y, xz[1]))
                if o is not None and o != net:
                    return True
                # Horizontal 8-neighbourhood on each intermediate layer: a
                # descent rung beside ANOTHER net's cross wire shorts it (MC
                # dust couples on the same layer) — measured on Control: n3's
                # descend rung at (17,5,71) sat next to n4's cross at
                # (17,5,72) and produced 5 shorts, because the check only
                # looked down its own column.
                for dx, dz in _PLANE_SHELL:
                    o = self.owner3d.get((xz[0] + dx, y, xz[1] + dz))
                    if o is not None and o != net:
                        return True
        return False

    def _materialize(self, nets, placements, bridges):
        res = BuildResult({}, set(), {}, dict(bridges), [], {},
                          torches=[], torch_nets={},
                          wall_torches=[], wall_torch_nets={})
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
                    res.torch_nets[(pl[1], pl[2], pl[3])] = net
                elif role == "wtorch":
                    res.wall_torches.append(((pl[1], pl[2], pl[3]), pl[4]))
                    res.wall_torch_nets[(pl[1], pl[2], pl[3])] = net
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
