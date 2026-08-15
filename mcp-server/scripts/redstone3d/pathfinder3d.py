"""
pathfinder3d.py — PathFinder negotiated-congestion router with DYNAMIC layers.

The 2-D version proved the negotiation core (0 shorts) but ran out of y0 plane
space: the hard repair dropped nets it could not re-place (11 nets including
every PI starved, outputs stuck). This version extends the graph into the third
dimension with the VERIFIED via gadgets from via_gadget.py:

  rise: (x, y, z) -> repeater riser -> (x+3, y+2, z)     [non-inverting]
  drop: (x, y+2, z) -> +x staircase -> (x+2, y, z)       [non-inverting]

Signal layers sit at y0 + 2*k (k = 0..L-1) so layers never couple across the
gap (measured: 2+ layers apart = isolated). A route starts on y0 at its source,
rises when the plane is congested, and drops back to y0 for the sink feed —
the Dijkstra sees the whole 3-D graph, so where to rise/drop is its choice.

LAYER SELF-ADAPTATION: route() tries 1 layer first; if the negotiation+repair
cannot converge (shorts or unfed nets), it adds a layer and re-runs. alu1's
short nets converge in 1-2 layers; deeper modules get as many as they need —
that is the generalization guarantee.
"""
from __future__ import annotations
import heapq
import sys, os, json, time
from collections import deque
from typing import Dict, List, Tuple, Set, Optional

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))

import coupling
from placer import Placement

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
XZ = Tuple[int, int]
P3 = Tuple[int, int, int]

P_GROW = 1.6
P0 = 1.0
RISE_COST = 12.0     # a riser eats 4 cells + a repeater. Cheap vias made
DROP_COST = 10.0     # every net bridge trivial obstacles; their y1 dust
                     # couples see-below with the y0 plane, tripling the
                     # conflict surface (2L shorts oscillated 280-760 vs the
                     # 2-D plateau ~200). Vias must stay a long-line tool.
TURN_PEN = 3.0       # per-turn cost: the history-polluted plane forced
JOG_PEN = 2.0       # per-cell cost of a drop landing away from its feed: a
                    # long y0 jog after the staircase decays the last of the
                    # signal (measured: n6's landing at power 1 died on a
                    # 3-cell jog). Drops are priced to land on the feed.
                     # serpentine paths whose straight segments were <13
                     # cells, so NO refresh repeater ever fit and 40-100-cell
                     # runs decayed to 0 (every stuck output traced to it).
                     # Turning is priced to keep runs straight.
S = "minecraft:stone"


class PathFinder3D:
    def __init__(self, pl: Placement, margin: int = 16, max_layers: int = 5,
                 p_cap: float = 128.0, fanout_mult: float = 8.0):
        self.pl = pl
        mn, mx = pl.bounds
        self.bx = (mn[0] - margin, mx[0] + margin)
        self.bz = (mn[2] - margin, mx[2] + margin)
        self.y0 = mn[1]
        # hard obstacles per layer: y0 cells (4-neighbour keep-out, measured —
        # grazing a cell couples into its internals), y1 = cell top row.
        base_cells = set((p[0], p[2]) for p in pl.occupancy)
        self.cell_xz: Set[XZ] = set(base_cells)
        for (x, z) in base_cells:
            for dx, dz in ORTH:
                self.cell_xz.add((x + dx, z + dz))
        self.cell_xz_y1: Set[XZ] = set()
        self.cell_xz_base: Set[XZ] = set()
        for (x, y, z) in pl.occupancy:
            if y == mn[1] + 1:
                self.cell_xz_y1.add((x, z))
            if y == mn[1]:
                self.cell_xz_base.add((x, z))
        self.pin_xz: Set[XZ] = set()
        for net, pos in pl.net_sources.items():
            self.pin_xz.add((pos[0], pos[2]))
        for net, sinks in pl.net_sinks.items():
            for pos in sinks:
                self.pin_xz.add((pos[0], pos[2]))
        self.h: Dict[P3, float] = {}
        self.p = P0
        self.p_cap = p_cap
        self.fanout_mult = fanout_mult
        self.max_layers = max_layers
        self.fanout_nets: Set[str] = set()
        self.layers: List[int] = [self.y0]
        self.nets = [n for n in pl.net_sinks
                     if pl.net_sources.get(n) and pl.net_sinks.get(n)]
        # FANOUT EXPRESS LANE: PI nets are the long-haulers (n2's y0 run
        # caused 27/38 residual shorts; n5's serpentine 90-cell y0 run decayed
        # to 0 at its gate feeds because no refresh repeater fit its turns).
        # ALL PIs get the expensive y0 plane so their runs live upstairs on
        # straight lanes where repeaters fit.
        self.fanout_nets = {n for n in self.nets
                            if n in self.pl.primary_inputs}

    # ---------- geometry ----------
    def _in_box(self, xz: XZ) -> bool:
        return self.bx[0] <= xz[0] <= self.bx[1] and \
               self.bz[0] <= xz[1] <= self.bz[1]

    def _blocked_at(self, x: int, y: int, z: int, goal: P3) -> bool:
        """Hard obstacles at (x,y,z): out of box, cell bodies (per layer),
        pins on y0."""
        if y == goal[1] and x == goal[0] and z == goal[2]:
            return False
        if not self._in_box((x, z)):
            return True
        if y == self.y0:
            if (x, z) in self.cell_xz or (x, z) in self.pin_xz:
                return True
        elif y == self.y0 + 1:
            if (x, z) in self.cell_xz_y1:
                return True
        elif y >= self.y0 + 2:
            # upper layers must stay off the cell's footprint: a fanout lane
            # running directly over a gate's body couples into its y1
            # internals (wall torches read their mount) via see-below and
            # flips the gate (measured: 12 gates wrong at 0 shorts once n2
            # moved upstairs). The 1-cell keep-out ring is fine to overfly.
            if (x, z) in self.cell_xz_base:
                return True
        return False

    def _cost(self, x: int, y: int, z: int, p: float) -> float:
        return 1.0 + self.h.get((x, y, z), 0.0) * p

    def _via_cost(self, net: str, kind: str) -> float:
        """PI nets (long fanout, the worst plane-hoggers — n2 alone caused
        27/38 residual shorts) get cheap vias so their runs move upstairs
        and free the y0 plane for local wiring."""
        return RISE_COST if kind == "rise" else DROP_COST

    def _rise_cells(self, x: int, y: int, z: int) -> List[tuple]:
        """placements for a riser starting from dust at (x,y,z), arriving at
        (x+3, y+2, z). From via_gadget.rise_cells (verified T2). The repeater
        must sit on a solid block: on y0 the floor provides it; on raised
        layers a passive support is added (MCHPRS tolerates a floating
        repeater, but the real-game build pops it off — in-game rule: only
        full blocks may float)."""
        out = [("rep", x + 1, y, z, "west"),
               ("block", x + 2, y, z), ("dust", x + 2, y + 1, z),
               ("block", x + 3, y + 1, z), ("dust", x + 3, y + 2, z)]
        if y > self.y0:
            out.append(("support", x + 1, y - 1, z))
        return out

    def _drop_cells(self, x: int, y: int, z: int) -> List[tuple]:
        """placements for a 2-level staircase from dust at (x,y,z) to
        (x+2, y-2, z). From via_gadget.drop_cells. The START dust must sit on
        a POWERABLE block: the diagonal step-down does not conduct off a
        glass support (measured: upper on glass -> lower step reads 0; upper
        on stone -> reads 14), so every drop start gets its own stone block.
        Step 1 sits on (x+1, y-2); the landing on the floor or (x+2, y-3)."""
        out = []
        # stone under the START dust (required for the step-down connection)
        if y - 1 > self.y0:
            out.append(("block", x, y - 1, z))
        # step 1: (x+1, y-1) dust on support (x+1, y-2)
        out.append(("block", x + 1, y - 2, z))
        out.append(("dust", x + 1, y - 1, z))
        # step 2: (x+2, y-2) dust; support only if above y0 floor
        if y - 2 > self.y0:
            out.append(("block", x + 2, y - 3, z))
        out.append(("dust", x + 2, y - 2, z))
        return out

    def _via_blocked(self, cells: List[tuple], net: str, goal: P3,
                     tree: Optional[Set[P3]] = None) -> bool:
        """Hard check for a via: no cell of its footprint may sit on a hard
        obstacle, and NO elevated via interior dust may neighbour a gate
        body — a riser's y1 dust beside a cell's mount powers it via
        see-below (P4) and flips the gate regardless of its input (measured:
        gates dead at 0 shorts once fanout lanes moved upstairs).
        With `tree`, the net's OWN already-placed dust is also forbidden on
        the footprint's solid cells: the emit writes repeaters after wires,
        so a tree wire on a riser's rep/block cell overwrites the gadget and
        severs the earlier sink's branch (measured: n5's express lane)."""
        for c in cells:
            if c[0] == "dust":
                x, y, z = c[1], c[2], c[3]
                if self._blocked_at(x, y, z, goal):
                    return True
                if y != self.y0:
                    for dx, dz in ORTH:
                        if (x + dx, z + dz) in self.cell_xz_base:
                            return True
            elif c[0] in ("block", "rep"):
                x, y, z = c[1], c[2], c[3]
                if self._blocked_at(x, y, z, goal):
                    return True
                if tree is not None and (x, y, z) in tree:
                    return True
        return False

    def _occ_penalty(self, cells: List[tuple], occ3: Dict[P3, str],
                     net: str) -> float:
        """Soft penalty: how much this via's footprint couples with foreign
        conductors already placed."""
        pen = 0.0
        for c in cells:
            if c[0] not in ("dust", "rep"):
                continue
            a = (c[1], c[2], c[3])
            for dx, dy, dz in coupling.shell_offsets():
                q = (a[0] + dx, a[1] + dy, a[2] + dz)
                o = occ3.get(q)
                if o is not None and o != net and o != f"{net}:torch":
                    if coupling.couples(a, q, occ3):
                        pen += 6.0
        return pen

    @staticmethod
    def _invalidate_support_shadow(dist, prev, sup: P3):
        """A via just registered a conductor at `sup` (interior dust/repeater).
        Any ALREADY-relaxed plane node whose support cell is `sup` would float
        in-game (a wire cannot sit on a wire); drop those dist entries so the
        final path cannot pass through them."""
        for node in list(dist.keys()):
            if node[1] > sup[1] and (node[0], node[1] - 1, node[2]) == sup:
                del dist[node]
                prev.pop(node, None)

    # ---------- one sink's Dijkstra over the 3-D graph ----------
    def _sink_route(self, tree: Set[P3], goal: P3, net: str,
                    occ3: Dict[P3, str],
                    reserved: Optional[Dict[P3, P3]] = None
                    ) -> Optional[List[P3]]:
        """Wavefront Dijkstra from the whole tree. Node = (x, y, z) with
        y in self.layers. Edges: same-layer 4-neighbour dust steps, plus
        RISE (y -> y+2, +3 x) and DROP (y -> y-2, +2 x) via edges.
        `reserved` maps this net's own via footprint cells (rep/block) to the
        via's start node: a later sink's plane dust must not walk onto them,
        and a DIFFERENT via may not claim them — the emit writes wires AFTER
        supports and repeaters AFTER wires, so a tree dust on a riser's
        rep/block cell overwrites the gadget and kills the whole net
        (measured: n5's y2 dust ran through its own riser rep and the entire
        express lane went dark). The SAME start reusing its own footprint is
        allowed (multi-sink nets share one riser)."""
        p = self.p
        s = self.pl.net_sources[net]
        if reserved is None:
            reserved = {}
        layer_idx = {y: i for i, y in enumerate(self.layers)}
        dist = {c: (0.0, -1) for c in tree}
        prev: Dict[P3, Tuple[P3, str]] = {}
        pq = [(0.0, c) for c in tree]
        heapq.heapify(pq)
        while pq:
            d, cur = heapq.heappop(pq)
            if cur not in dist or d > dist[cur][0]:
                continue
            if cur == goal:
                path = [cur]
                via_starts: Set[P3] = set()
                while path[-1] in prev:
                    par, kind = prev[path[-1]]
                    if kind in ("rise", "drop"):
                        via_starts.add(par)
                    path.append(par)
                path.reverse()
                return path, via_starts
            x, y, z = cur
            _, pdir = dist[cur]
            # same-layer dust steps
            for dx, dz in ORTH:
                nx = (x + dx, y, z + dz)
                if nx in reserved:
                    continue
                if self._blocked_at(nx[0], nx[1], nx[2], goal):
                    continue
                if net in self.fanout_nets and nx[0] < s[0]:
                    # PI lines must never detour WEST of their source: the
                    # only way back east passes the riser's own rep cell and
                    # the emit severs the feed (measured: n4 rose at x=-3).
                    continue
                if y > self.y0:
                    o = reserved.get((nx[0], y - 1, nx[2]))
                    if o is not None and o[1] != "solid":
                        # a raised plane node's support cell must be empty or
                        # solid — over a repeater/via-interior the wire pops
                        # in-game (measured: (73,2,19) over a riser interior)
                        continue
                ndir = 0 if (dx, dz) == (1, 0) else 1 if (dx, dz) == (-1, 0) \
                    else 2 if (dx, dz) == (0, 1) else 3
                extra = 0.0 if (pdir == -1 or pdir == ndir) else TURN_PEN
                step = self._cost(nx[0], nx[1], nx[2], p)
                if y == self.y0 and net in self.fanout_nets:
                    step *= self.fanout_mult
                nd = d + extra + step
                if nd < dist.get(nx, (1e9, -1))[0]:
                    dist[nx] = (nd, ndir)
                    prev[nx] = (cur, "plane")
                    heapq.heappush(pq, (nd, nx))
            # RISE: (x,y,z) -> (x+3, y+2, z)
            if y + 2 in self.layers:
                rc = self._rise_cells(x, y, z)
                # reject when the plane wavefront ALREADY reached a footprint
                # cell (the emit would let the riser's repeater/block overwrite
                # the earlier wire, severing that branch — reserved blocks the
                # later order; this blocks the earlier one)
                if prev.get((x, y, z), (None, ""))[0] != (x + 1, y, z) and \
                   not self._via_blocked(rc, net, goal, tree) and \
                   self._res_ok(reserved, (x, y, z),
                                ((x + 1, y, z),),
                                ((x + 2, y, z), (x + 3, y + 1, z)),
                                ((x + 2, y + 1, z), (x + 3, y + 2, z))):
                    top = (x + 3, y + 2, z)
                    pen = self._occ_penalty(rc, occ3, net)
                    nd = d + self._via_cost(net, "rise") + pen \
                        + self._cost(*top, p)
                    if nd < dist.get(top, (1e9, -1))[0]:
                        dist[top] = (nd, -1)
                        prev[top] = (cur, "rise")
                        heapq.heappush(pq, (nd, top))
                        reserved[(x + 1, y, z)] = ((x, y, z), "rep")
                        reserved[(x + 2, y, z)] = ((x, y, z), "solid")
                        reserved[(x + 3, y + 1, z)] = ((x, y, z), "solid")
                        # interior dust: a raised plane node above it would
                        # need its support here — a wire cannot sit on a wire
                        # (in-game the dust pops; measured at (73,2,19))"""
                        reserved[(x + 2, y + 1, z)] = ((x, y, z), "rep")
                        self._invalidate_support_shadow(
                            dist, prev, (x + 2, y + 1, z))
            # DROP: (x,y,z) -> (x+2, y-2, z)
            if y - 2 in self.layers:
                dc = self._drop_cells(x, y, z)
                if not self._via_blocked(dc, net, goal, tree) and \
                   self._res_ok(reserved, (x, y, z),
                                (),
                                ((x, y - 1, z), (x + 1, y - 2, z),
                                 (x + 2, y - 3, z)),
                                ((x + 1, y - 1, z), (x + 2, y - 2, z))):
                    bot = (x + 2, y - 2, z)
                    pen = self._occ_penalty(dc, occ3, net)
                    jog = abs(bot[0] - goal[0]) + abs(bot[2] - goal[2])
                    nd = d + self._via_cost(net, "drop") + pen \
                        + JOG_PEN * jog + self._cost(*bot, p)
                    if nd < dist.get(bot, (1e9, -1))[0]:
                        dist[bot] = (nd, -1)
                        prev[bot] = (cur, "drop")
                        heapq.heappush(pq, (nd, bot))
                        reserved[(x, y - 1, z)] = ((x, y, z), "solid")
                        reserved[(x + 1, y - 2, z)] = ((x, y, z), "solid")
                        reserved[(x + 2, y - 3, z)] = ((x, y, z), "solid")
                        reserved[(x + 1, y - 1, z)] = ((x, y, z), "rep")
                        self._invalidate_support_shadow(
                            dist, prev, (x + 1, y - 1, z))
        return None, None

    def _path_to_placements(self, path: List[P3], prev: Dict[P3, P3],
                            net: str) -> List[tuple]:
        """Convert a node path (with via edges) to typed placements. A rise or
        drop edge is recognised by the coordinate jump between consecutive
        nodes."""
        out: List[tuple] = []
        for i in range(len(path) - 1):
            a, b = path[i], path[i + 1]
            dy = b[1] - a[1]
            if dy == 2:                      # rise edge
                out += self._rise_cells(a[0], a[1], a[2])
            elif dy == -2:                   # drop edge
                out += self._drop_cells(a[0], a[1], a[2])
            else:                            # plain dust step
                pass
        # every node cell is dust (except via interiors)
        for node in path:
            out.append(("dust", node[0], node[1], node[2]))
        # supports for raised plane dust (y > y0): glass blocks under each
        for node in path:
            if node[1] > self.y0:
                out.append(("support", node[0], node[1] - 1, node[2]))
        return out

    @staticmethod
    def _res_ok(reserved: Dict[P3, tuple], start: P3, rep_cells, solid_cells,
                dust_cells) -> bool:
        """Refined via-footprint reservation check.
        rep_cells: exclusive (a repeater cannot share its cell with ANYTHING).
        solid_cells: stone may share with other vias' stone (solid+solid is
        the same block in the emit) but not with a repeater.
        dust_cells (via interiors/tops/landings): must not sit on another
        via's rep/solid — the wire would overwrite it in the emit."""
        for c in rep_cells:
            o = reserved.get(c)
            if o is not None and o[0] != start:
                return False
        for c in solid_cells:
            o = reserved.get(c)
            if o is not None and o[1] != "solid":
                return False
        for c in dust_cells:
            o = reserved.get(c)
            if o is not None and o[0] != start:
                return False
        return True

    def _contested(self, occ3: Dict[P3, str]) -> Set[P3]:
        out: Set[P3] = set()
        seen: Set[tuple] = set()
        for v, net in occ3.items():
            for dx, dy, dz in coupling.shell_offsets():
                q = (v[0] + dx, v[1] + dy, v[2] + dz)
                o = occ3.get(q)
                if o is None or o == net:
                    continue
                key = tuple(sorted([v, q]))
                if key in seen:
                    continue
                seen.add(key)
                if coupling.couples(v, q, occ3):
                    out.add(v)
                    out.add(q)
        # overlaps
        owners: Dict[P3, Set[str]] = {}
        for v, net in occ3.items():
            owners.setdefault(v, set()).add(net)
        for v, ns in owners.items():
            if len(ns) > 1:
                out.add(v)
        return out

    # ---------- negotiation ----------
    def _negotiate(self, max_rounds: int, verbose: bool):
        best = None
        best_key = (1 << 30, 1 << 30)
        for rnd in range(max_rounds):
            occ3: Dict[P3, str] = {}
            placements: Dict[str, List[tuple]] = {}
            for net in self.nets:
                s = self.pl.net_sources[net]
                src = (s[0], s[1], s[2])
                tree: Set[P3] = {src}
                ok = True
                sinks = sorted(self.pl.net_sinks[net],
                               key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                               reverse=True)
                via_starts: Set[P3] = set()
                reserved: Dict[P3, P3] = {}   # via footprint cell -> via start
                for k in sinks:
                    goal = (k[0] - 1, self.y0, k[2])
                    path, vs = self._sink_route(tree, goal, net, occ3,
                                                reserved)
                    if path is None:
                        ok = False
                        continue
                    if vs:
                        via_starts |= vs
                    for v in path:
                        tree.add(v)
                ps = self._net_placements(net, tree, via_starts)
                placements[net] = ps
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        occ3[(x, y, z)] = net
            shorts = coupling.count_shorts(occ3)
            contested = self._contested(occ3)
            n_unfed = sum(1 for n in self.nets
                          if not self._sink_fed(n, placements))
            if verbose:
                print(f"  {len(self.layers)}L round {rnd:2d}: p={self.p:6.1f} "
                      f"shorts={shorts:4d} contested={len(contested):5d} "
                      f"unfed={n_unfed}", flush=True)
            # fully-fed solutions first: repair can clear a few shorts, but
            # it cannot invent a feed for a net the negotiation starved
            # (PIs are never dropped). A (unfed=0, shorts=3) round usually
            # repairs to (0,0); a (unfed=1, shorts=0) round stays stuck.
            key = (n_unfed, shorts)
            if key < best_key:
                best_key = key
                best = placements
            if shorts == 0 and n_unfed == 0:
                return best, 0
            for v in contested:
                self.h[v] = self.h.get(v, 0.0) + 1.0
            self.p = min(self.p * P_GROW, self.p_cap)
        return best, best_key[0]

    def _net_placements(self, net: str, tree: Set[P3],
                        via_starts: Set[P3]) -> List[tuple]:
        """Rebuild placements from the final tree. Via edges are recorded
        EXPLICITLY by the Dijkstra (a node pair 2 levels apart was previously
        guessed from geometry, and independent tree segments got fake vias
        bolted on — extra conflict cells the repair could never clear)."""
        out: List[tuple] = []
        via_blocks: Set[P3] = set()
        via_dust: Set[P3] = set()
        for (x, y, z) in via_starts:
            if (x + 3, y + 2, z) in tree and y + 2 in self.layers:
                rc = self._rise_cells(x, y, z)
                out += rc
                for c in rc:
                    if c[0] in ("block", "rep"):
                        via_blocks.add((c[1], c[2], c[3]))
                    if c[0] in ("dust", "rep"):
                        via_dust.add((c[1], c[2], c[3]))
            if (x + 2, y - 2, z) in tree and y - 2 in self.layers:
                dc = self._drop_cells(x, y, z)
                out += dc
                for c in dc:
                    if c[0] == "block":
                        via_blocks.add((c[1], c[2], c[3]))
                    if c[0] == "dust":
                        via_dust.add((c[1], c[2], c[3]))
        for node in sorted(tree):
            if node in via_blocks:
                # the via's repeater/block WINS at emit (written after wires),
                # so a tree dust here would be overwritten and its branch
                # severed silently. Skip it: placements must equal the
                # emitted reality, and the fed-check then reports the severed
                # branch honestly so repair reroutes it.
                continue
            if node[1] > self.y0 and \
                    (node[0], node[1] - 1, node[2]) in via_dust:
                # a raised plane node whose support cell is a via conductor
                # (interior dust/repeater) would float in-game and pop off
                # (measured: 11 such cells on the first ring-keepout route).
                # Drop the node: the fed-check then reports the severed
                # branch and repair reroutes around the collision.
                continue
            out.append(("dust", node[0], node[1], node[2]))
            if node[1] > self.y0 and (node[0], node[1] - 1, node[2]) \
                    not in via_blocks:
                out.append(("support", node[0], node[1] - 1, node[2]))
        return out

    def _sink_fed(self, net: str, placements: Dict[str, List[tuple]]) -> bool:
        """POWER-aware feed check: every sink's west feed cell must receive
        power >= 1 under the refresh3d insertion model. Topology is NOT
        enough — the old walk connected a 40-cell serpentine whose signal had
        decayed to 0, so the router converged with dead gates (stuck outputs)
        while reporting unfed=0. refresh3d simulates the same repeater
        insertion the materializer performs, so check and reality agree."""
        s = self.pl.net_sources.get(net)
        if s is None or net not in placements:
            return False
        import refresh3d
        feeds = refresh3d.feed_powers(net, placements[net], s,
                                      self.pl.net_sinks[net])
        return all(p >= 1 for p in feeds.values())

    # ---------- hard repair (drop semantics, 3-D) ----------
    def _hard_route_net(self, net: str, frozen_occ: Dict[P3, str]
                        ) -> Optional[List[tuple]]:
        s = self.pl.net_sources[net]
        src = (s[0], s[1], s[2])
        tree: Set[P3] = {src}
        via_starts: Set[P3] = set()
        reserved: Dict[P3, P3] = {}
        for k in sorted(self.pl.net_sinks[net],
                        key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                        reverse=True):
            goal = (k[0] - 1, self.y0, k[2])
            dist = {c: (0, -1) for c in tree}
            prev: Dict[P3, Tuple[P3, str]] = {}
            pq = [(0, c) for c in tree]
            heapq.heapify(pq)
            found = None
            while pq:
                d, cur = heapq.heappop(pq)
                if cur not in dist or d > dist[cur][0]:
                    continue
                if cur == goal:
                    found = cur
                    break
                x, y, z = cur
                _, pdir = dist[cur]
                for dx, dz in ORTH:
                    nx = (x + dx, y, z + dz)
                    if nx in reserved:
                        continue
                    if self._blocked_at(nx[0], nx[1], nx[2], goal):
                        continue
                    if self._coupled(nx, net, frozen_occ):
                        continue
                    if net in self.fanout_nets and nx[0] < s[0]:
                        continue
                    if y > self.y0:
                        o = reserved.get((nx[0], y - 1, nx[2]))
                        if o is not None and o[1] != "solid":
                            continue
                    ndir = 0 if (dx, dz) == (1, 0) else 1 if (dx, dz) == (-1, 0) \
                        else 2 if (dx, dz) == (0, 1) else 3
                    extra = 0.0 if (pdir == -1 or pdir == ndir) else TURN_PEN
                    step = 1
                    if y == self.y0 and net in self.fanout_nets:
                        step = self.fanout_mult
                    nd = d + extra + step
                    if nd < dist.get(nx, (1e9, -1))[0]:
                        dist[nx] = (nd, ndir)
                        prev[nx] = (cur, "plane")
                        heapq.heappush(pq, (nd, nx))
                if y + 2 in self.layers:
                    rc = self._rise_cells(x, y, z)
                    top = (x + 3, y + 2, z)
                    if prev.get((x, y, z), (None, ""))[0] != (x + 1, y, z) and \
                       not self._via_blocked(rc, net, goal, tree) and \
                       not self._via_coupled(rc, net, frozen_occ) and \
                       not self._coupled(top, net, frozen_occ) and \
                       self._res_ok(reserved, (x, y, z),
                                    ((x + 1, y, z),),
                                    ((x + 2, y, z), (x + 3, y + 1, z)),
                                    ((x + 2, y + 1, z), (x + 3, y + 2, z))):
                        nd = d + self._via_cost(net, "rise")
                        if nd < dist.get(top, (1e9, -1))[0]:
                            dist[top] = (nd, -1)
                            prev[top] = (cur, "rise")
                            heapq.heappush(pq, (nd, top))
                            reserved[(x + 1, y, z)] = ((x, y, z), "rep")
                            reserved[(x + 2, y, z)] = ((x, y, z), "solid")
                            reserved[(x + 3, y + 1, z)] = ((x, y, z), "solid")
                            reserved[(x + 2, y + 1, z)] = ((x, y, z), "rep")
                            self._invalidate_support_shadow(
                                dist, prev, (x + 2, y + 1, z))
                if y - 2 in self.layers:
                    dc = self._drop_cells(x, y, z)
                    bot = (x + 2, y - 2, z)
                    if not self._via_blocked(dc, net, goal, tree) and \
                       not self._via_coupled(dc, net, frozen_occ) and \
                       not self._coupled(bot, net, frozen_occ) and \
                       self._res_ok(reserved, (x, y, z),
                                    (),
                                    ((x, y - 1, z), (x + 1, y - 2, z),
                                     (x + 2, y - 3, z)),
                                    ((x + 1, y - 1, z), (x + 2, y - 2, z))):
                        jog = abs(bot[0] - goal[0]) + abs(bot[2] - goal[2])
                        nd = d + self._via_cost(net, "drop") + JOG_PEN * jog
                        if nd < dist.get(bot, (1e9, -1))[0]:
                            dist[bot] = (nd, -1)
                            prev[bot] = (cur, "drop")
                            heapq.heappush(pq, (nd, bot))
                            reserved[(x, y - 1, z)] = ((x, y, z), "solid")
                            reserved[(x + 1, y - 2, z)] = ((x, y, z), "solid")
                            reserved[(x + 2, y - 3, z)] = ((x, y, z), "solid")
                            reserved[(x + 1, y - 1, z)] = ((x, y, z), "rep")
                            self._invalidate_support_shadow(
                                dist, prev, (x + 1, y - 1, z))
            if found is None:
                return None
            path = [found]
            while path[-1] in prev:
                par, kind = prev[path[-1]]
                if kind in ("rise", "drop"):
                    via_starts.add(par)
                path.append(par)
            path.reverse()
            for v in path:
                tree.add(v)
        return self._net_placements(net, tree, via_starts)

    def _coupled(self, node: P3, net: str, frozen_occ: Dict[P3, str]) -> bool:
        for dx, dy, dz in coupling.shell_offsets():
            q = (node[0] + dx, node[1] + dy, node[2] + dz)
            fo = frozen_occ.get(q)
            if fo is not None and fo != net and fo != f"{net}:torch":
                if coupling.couples(node, q, frozen_occ):
                    return True
        return False

    def _via_coupled(self, cells: List[tuple], net: str,
                     frozen_occ: Dict[P3, str]) -> bool:
        """True if any CONDUCTING cell of a via footprint couples with a
        frozen foreign conductor (blocks are passive, dust/repeaters are not)."""
        for c in cells:
            if c[0] not in ("dust", "rep"):
                continue
            if self._coupled((c[1], c[2], c[3]), net, frozen_occ):
                return True
        return False

    def repair(self, placements: Dict[str, List[tuple]],
               max_rounds: int = 10) -> Dict[str, List[tuple]]:
        """Drop-semantics hard repair, mirroring the measured 2-D structure:
        freeze clean nets, hard-reroute the conflicting ones, drop those with
        no hard route, soft-route the dropped back (no overlap), then polish.
        PI lines are never dropped (a missing PI starves every downstream gate
        and stuck the whole ALU in 2-D)."""
        original = {n: list(ps) for n, ps in placements.items()}
        dropped_ever: Set[str] = set()
        for rnd in range(max_rounds):
            occ3: Dict[P3, str] = {}
            for n, ps in placements.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        occ3[(x, y, z)] = n
            shorts = coupling.count_shorts(occ3)
            missing = [n for n in self.nets
                      if n not in placements or
                      not self._sink_fed(n, placements)]
            if shorts == 0 and not missing:
                return placements
            bad: Set[str] = set()
            seen: Set[tuple] = set()
            for v, net in occ3.items():
                for dx, dy, dz in coupling.shell_offsets():
                    q = (v[0] + dx, v[1] + dy, v[2] + dz)
                    o = occ3.get(q)
                    if o is None or o == net:
                        continue
                    key = tuple(sorted([v, q]))
                    if key in seen:
                        continue
                    seen.add(key)
                    if coupling.couples(v, q, occ3):
                        bad.add(net)
                        bad.add(o)
            # UNFED nets must be re-routed too: a net whose sink's Dijkstra
            # failed during negotiation kept a PARTIAL tree that carries no
            # shorts — the conflict scan never saw it, so it stayed broken
            # forever (measured: n17's sink1 feed free on all sides yet dark).
            for n in self.nets:
                if n not in placements or not self._sink_fed(n, placements):
                    bad.add(n)
            frozen = {n: placements[n] for n in placements if n not in bad}
            fo3: Dict[P3, str] = {}
            for n, ps in frozen.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        fo3[(x, y, z)] = n
            for net, pos in self.pl.primary_inputs.items():
                fo3[(pos[0], pos[1], pos[2])] = net
                fo3[(pos[0] - 1, pos[1], pos[2])] = net
            new_place = dict(frozen)
            dropped: Set[str] = set()
            for n in sorted(bad, key=lambda n: (-len(self.pl.net_sinks[n]), n)):
                ps = self._hard_route_net(n, fo3)
                if ps is None:
                    if n in self.pl.primary_inputs:
                        new_place[n] = placements[n]
                    else:
                        dropped.add(n)
                    continue
                new_place[n] = ps
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        fo3[(x, y, z)] = n
            placements = new_place
            dropped_ever |= dropped
            print(f"  repair {rnd}: bad={len(bad)} dropped={len(dropped)}",
                  flush=True)
        # soft-route dropped nets back — no overlap, adjacency allowed; a
        # missing net floats its sinks (measured in 2-D: full stuck output)
        for n in sorted(dropped_ever):
            occ_others: Set[P3] = set()
            for m, ps in placements.items():
                if m == n:
                    continue
                for role, x, y, z, *rest in ps:
                    if role == "dust":
                        occ_others.add((x, y, z))
            ps = self._soft_route_net(n, occ_others)
            # per-sink independence may return a PARTIAL tree (a hard sink
            # skipped); that leaves the net electrically unfed — measured:
            # negotiation fed 29/29 but repair ended at unfed=17. Only accept
            # a fully-fed result; otherwise reinstate the pre-repair line.
            if ps is not None:
                trial = dict(placements)
                trial[n] = ps
                if not self._sink_fed(n, trial):
                    ps = None
            if ps is None:
                ps = original.get(n)
            if ps is not None:
                placements[n] = ps
        # polish: keep coverage, only reduce shorts
        for rnd in range(4):
            occ3: Dict[P3, str] = {}
            for n, ps in placements.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        occ3[(x, y, z)] = n
            bad: Set[str] = set()
            seen: Set[tuple] = set()
            for v, net in occ3.items():
                for dx, dy, dz in coupling.shell_offsets():
                    q = (v[0] + dx, v[1] + dy, v[2] + dz)
                    o = occ3.get(q)
                    if o is None or o == net:
                        continue
                    key = tuple(sorted([v, q]))
                    if key in seen:
                        continue
                    seen.add(key)
                    if coupling.couples(v, q, occ3):
                        bad.add(net)
                        bad.add(o)
            if not bad:
                break
            frozen = {n: placements[n] for n in placements if n not in bad}
            fo3: Dict[P3, str] = {}
            for n, ps in frozen.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        fo3[(x, y, z)] = n
            for net, pos in self.pl.primary_inputs.items():
                fo3[(pos[0], pos[1], pos[2])] = net
                fo3[(pos[0] - 1, pos[1], pos[2])] = net
            new_place = dict(frozen)
            for n in sorted(bad, key=lambda n: (-len(self.pl.net_sinks[n]), n)):
                ps = self._hard_route_net(n, fo3)
                if ps is None:
                    new_place[n] = placements[n]   # never lose coverage
                    continue
                new_place[n] = ps
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        fo3[(x, y, z)] = n
            placements = new_place
            print(f"  polish {rnd}: bad={len(bad)}", flush=True)
        # soft polish measured COUNTERPRODUCTIVE (38 -> 1247 shorts on the
        # best sweep point): soft lines chasing history costs re-entangle the
        # clean bulk. The hard repair alone reached 38 shorts / 0 missing.
        placements = self._soft_polish(placements, rounds=0)
        return placements

    def _soft_polish(self, placements: Dict[str, List[tuple]],
                     rounds: int = 10) -> Dict[str, List[tuple]]:
        """Final convergence pass: the hard polish leaves a small set of nets
        whose conflicts are unfixable under hard constraints (measured: 38
        shorts, 0 missing at the best sweep point). Re-negotiate ONLY the
        conflicting nets under the accumulated history cost for a few rounds —
        each round bumps history on the round's conflict cells, so the last
        few couplings negotiate apart exactly like the main loop, but only
        the conflicting few move (the clean bulk stays frozen)."""
        for rnd in range(rounds):
            occ3: Dict[P3, str] = {}
            for n, ps in placements.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        occ3[(x, y, z)] = n
            bad: Set[str] = set()
            contested: Set[P3] = set()
            seen: Set[tuple] = set()
            for v, net in occ3.items():
                for dx, dy, dz in coupling.shell_offsets():
                    q = (v[0] + dx, v[1] + dy, v[2] + dz)
                    o = occ3.get(q)
                    if o is None or o == net:
                        continue
                    key = tuple(sorted([v, q]))
                    if key in seen:
                        continue
                    seen.add(key)
                    if coupling.couples(v, q, occ3):
                        bad.add(net)
                        bad.add(o)
                        contested.add(v)
                        contested.add(q)
            if not bad:
                return placements
            for v in contested:
                self.h[v] = self.h.get(v, 0.0) + 1.0
            for n in sorted(bad, key=lambda n: (-len(self.pl.net_sinks[n]), n)):
                if n in self.pl.primary_inputs:
                    continue      # PI lines stay; others route around them
                occ_others: Set[P3] = set()
                for m, ps in placements.items():
                    if m == n:
                        continue
                    for role, x, y, z, *rest in ps:
                        if role == "dust":
                            occ_others.add((x, y, z))
                ps = self._soft_route_net(n, occ_others)
                if ps is not None:
                    placements[n] = ps
        return placements

    def _soft_route_net(self, net: str, occupied: Set[P3]
                        ) -> Optional[List[tuple]]:
        """Soft re-route of one net over the 3-D graph: negotiation cost
        (1 + h*p), no coupling checks, but never sharing a cell with another
        net (overlap kills the earlier net's wire in the emit)."""
        s = self.pl.net_sources[net]
        src = (s[0], s[1], s[2])
        tree: Set[P3] = {src}
        via_starts: Set[P3] = set()
        reserved: Dict[P3, P3] = {}
        p = self.p
        for k in sorted(self.pl.net_sinks[net],
                        key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]),
                        reverse=True):
            goal = (k[0] - 1, self.y0, k[2])
            dist = {c: (0.0, -1) for c in tree}
            prev: Dict[P3, Tuple[P3, str]] = {}
            pq = [(0.0, c) for c in tree]
            heapq.heapify(pq)
            found = None
            while pq:
                d, cur = heapq.heappop(pq)
                if cur not in dist or d > dist[cur][0]:
                    continue
                if cur == goal:
                    found = cur
                    break
                x, y, z = cur
                _, pdir = dist[cur]
                for dx, dz in ORTH:
                    nx = (x + dx, y, z + dz)
                    if nx in reserved:
                        continue
                    if self._blocked_at(nx[0], nx[1], nx[2], goal):
                        continue
                    if nx in occupied and nx != goal:
                        continue
                    if net in self.fanout_nets and nx[0] < s[0]:
                        continue
                    if y > self.y0:
                        o = reserved.get((nx[0], y - 1, nx[2]))
                        if o is not None and o[1] != "solid":
                            continue
                    ndir = 0 if (dx, dz) == (1, 0) else 1 if (dx, dz) == (-1, 0) \
                        else 2 if (dx, dz) == (0, 1) else 3
                    extra = 0.0 if (pdir == -1 or pdir == ndir) else TURN_PEN
                    step = self._cost(nx[0], nx[1], nx[2], p)
                    if y == self.y0 and net in self.fanout_nets:
                        step *= self.fanout_mult
                    nd = d + extra + step
                    if nd < dist.get(nx, (1e9, -1))[0]:
                        dist[nx] = (nd, ndir)
                        prev[nx] = (cur, "plane")
                        heapq.heappush(pq, (nd, nx))
                if y + 2 in self.layers:
                    rc = self._rise_cells(x, y, z)
                    top = (x + 3, y + 2, z)
                    if prev.get((x, y, z), (None, ""))[0] != (x + 1, y, z) and \
                       not self._via_blocked(rc, net, goal, tree) and \
                       top not in occupied and \
                       self._res_ok(reserved, (x, y, z),
                                    ((x + 1, y, z),),
                                    ((x + 2, y, z), (x + 3, y + 1, z)),
                                    ((x + 2, y + 1, z), (x + 3, y + 2, z))):
                        nd = d + self._via_cost(net, "rise")
                        if nd < dist.get(top, (1e9, -1))[0]:
                            dist[top] = (nd, -1)
                            prev[top] = (cur, "rise")
                            heapq.heappush(pq, (nd, top))
                            reserved[(x + 1, y, z)] = ((x, y, z), "rep")
                            reserved[(x + 2, y, z)] = ((x, y, z), "solid")
                            reserved[(x + 3, y + 1, z)] = ((x, y, z), "solid")
                            reserved[(x + 2, y + 1, z)] = ((x, y, z), "rep")
                            self._invalidate_support_shadow(
                                dist, prev, (x + 2, y + 1, z))
                if y - 2 in self.layers:
                    dc = self._drop_cells(x, y, z)
                    bot = (x + 2, y - 2, z)
                    if not self._via_blocked(dc, net, goal, tree) and \
                       bot not in occupied and \
                       self._res_ok(reserved, (x, y, z),
                                    (),
                                    ((x, y - 1, z), (x + 1, y - 2, z),
                                     (x + 2, y - 3, z)),
                                    ((x + 1, y - 1, z), (x + 2, y - 2, z))):
                        jog = abs(bot[0] - goal[0]) + abs(bot[2] - goal[2])
                        nd = d + self._via_cost(net, "drop") + JOG_PEN * jog
                        if nd < dist.get(bot, (1e9, -1))[0]:
                            dist[bot] = (nd, -1)
                            prev[bot] = (cur, "drop")
                            heapq.heappush(pq, (nd, bot))
                            reserved[(x, y - 1, z)] = ((x, y, z), "solid")
                            reserved[(x + 1, y - 2, z)] = ((x, y, z), "solid")
                            reserved[(x + 2, y - 3, z)] = ((x, y, z), "solid")
                            reserved[(x + 1, y - 1, z)] = ((x, y, z), "rep")
                            self._invalidate_support_shadow(
                                dist, prev, (x + 1, y - 1, z))
            if found is None:
                continue          # this sink is unreachable; try the next
            path = [found]
            while path[-1] in prev:
                par, kind = prev[path[-1]]
                if kind in ("rise", "drop"):
                    via_starts.add(par)
                path.append(par)
            path.reverse()
            for v in path:
                tree.add(v)
        return self._net_placements(net, tree, via_starts)

    # ---------- top level: dynamic layers ----------
    def route(self, max_rounds: int = 40, verbose: bool = True,
              start_layers: int = 1
              ) -> Tuple[Dict[str, List[tuple]], int]:
        best = None
        best_shorts = 1 << 30
        best_missing = 1 << 30
        t0 = time.time()
        for n_layers in range(start_layers, self.max_layers + 1):
            self.layers = [self.y0 + 2 * i for i in range(n_layers)]
            self.h = {}
            self.p = P0
            if verbose:
                print(f"=== layers={n_layers} ({self.layers}) "
                      f"t={time.time()-t0:.0f}s ===", flush=True)
            placements, shorts = self._negotiate(max_rounds, verbose=verbose)
            placements = self.repair(placements, max_rounds=10)
            occ3: Dict[P3, str] = {}
            for n, ps in placements.items():
                for role, x, y, z, *rest in ps:
                    if role != "support":
                        occ3[(x, y, z)] = n
            shorts = coupling.count_shorts(occ3)
            missing = [n for n in self.nets
                      if n not in placements or
                      not self._sink_fed(n, placements)]
            print(f"  layers={n_layers}: shorts={shorts} "
                  f"unfed_nets={len(missing)} {sorted(missing)[:8]}",
                  flush=True)
            if shorts < best_shorts or (shorts == best_shorts and
                                        len(missing) < best_missing):
                best_shorts = shorts
                best_missing = len(missing)
                best = placements
            if shorts == 0 and not missing:
                return best, 0
        return best, best_shorts


def _main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth",
                                      "netlists.json")))
    nl = nls["alu1"]
    from placer import place
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PathFinder3D(pl, margin=16, max_layers=4)
    placements, shorts = pf.route(max_rounds=40)
    print(f"FINAL: shorts={shorts} nets={len(placements)}/29")


if __name__ == "__main__":
    _main()
