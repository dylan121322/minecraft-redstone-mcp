"""
refresh3d.py — FLOW-DIRECTED refresh-repeater insertion + power simulation for
pathfinder3d placements.

The old route_buildable._insert_repeaters seeded every layer's BFS from the
SOURCE's xz projection. A raised layer's segment is fed by a VIA (rise top /
drop landing), not by the source column — so the BFS never reached it and NO
refresh repeater was ever inserted upstairs. Every long raised run decayed to
0 at its gates (the stuck outputs: topologically fed, electrically dead).

Model (all verified in MCHPRS):
  * conductor graph: dust cells, 6-dir adjacency, plus via chains
      riser: (rx-1,ry,rz) -> (rx+1,ry+1,rz) -> (rx+2,ry+2,rz)   (regen: 15)
      drop : (x,y,z) -> (x+1,y-1,z) -> (x+2,y-2,z)              (-1 per step)
  * power: source emits 15 (PI redstone block / gate target stage);
    dust step -1; refresh repeater outputs 15; riser regen 15.
  * refresh repeaters are inserted on the fly: when the run since the last
    refresh reaches MAX_RUN-1 at a straight dust cell (one child, collinear),
    the cell becomes a repeater facing the reverse of the inflow direction.
    Feed cells (west of a gate pin) are never replaced.
  * `powers()` simulates with the same insertion, so the ROUTER's fed check
    (_sink_fed) and the MATERIALIZED world agree exactly.
"""
from __future__ import annotations
from collections import deque
from typing import Dict, List, Set, Tuple, Optional

P3 = Tuple[int, int, int]
H3 = [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0)]
FLOW_FACING = {(1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south"}
MAX_RUN = 14          # dust decays to 0 after 15 steps; refresh before that
MAX_RUN_REP = 10      # insert at the first straight cell with run >= this
# (was 13: the segment just before a drop start then delivered power 3,
#  the staircase ate 2, and a 3-cell y0 jog killed the feed — measured n6)


def _via_edges(ps: List[tuple]) -> List[Tuple[P3, P3]]:
    """Riser/drop electrical chains.

    RISER: detected from its repeater (the only "rep" placements): input dust
    (rx-1,ry,rz) -> interior (rx+1,ry+1,rz) -> top (rx+2,ry+2,rz).
    DROP: detected from the dust TRIPLE start (x,y,z), step (x+1,y-1,z),
    landing (x+2,y-2,z). The old block-based construction also matched RISER
    blocks ((bx-1,by+2) dust happens to exist one level above), fabricating
    phantom drop edges that let the model walk power BACKWARD through a
    riser — a riser's repeater blocks that path in the real world."""
    cells = {(p[1], p[2], p[3]) for p in ps if p[0] == "dust"}
    rep_pos = {(p[1], p[2], p[3]) for p in ps if p[0] == "rep"}
    edges: List[Tuple[P3, P3]] = []
    for (rx, ry, rz) in rep_pos:
        edges.append(((rx - 1, ry, rz), (rx + 1, ry + 1, rz)))
        edges.append(((rx + 1, ry + 1, rz), (rx + 2, ry + 2, rz)))
    for (x, y, z) in cells:
        if (x + 1, y - 1, z) in cells and (x + 2, y - 2, z) in cells:
            edges.append(((x, y, z), (x + 1, y - 1, z)))
            edges.append(((x + 1, y - 1, z), (x + 2, y - 2, z)))
    return edges


def _regen_edge(e: Tuple[P3, P3]) -> bool:
    """True for riser edges (repeater regenerates to 15). Drop edges decay."""
    a, b = e
    return b[1] > a[1]


def flow_model(net: str, ps: List[tuple], src: P3, feed_cells: Set[P3]):
    """Build the oriented flow tree from src, insert refresh repeaters on the
    fly, and return (powers, reps) where reps = [(pos, facing), ...] to
    REPLACE dust cells."""
    dust = {(p[1], p[2], p[3]) for p in ps if p[0] == "dust"}
    via_edges = _via_edges(ps)
    via_map: Dict[P3, List[P3]] = {}
    for (a, b) in via_edges:
        via_map.setdefault(a, []).append(b)
    # cells where a refresh repeater must NOT go: gate feeds, the source,
    # via interiors, and a riser's INPUT dust (a repeater reading the back of
    # a repeater is electrically undefined here).
    riser_inputs = {(rx - 1, ry, rz)
                    for (rx, ry, rz) in {(p[1], p[2], p[3]) for p in ps
                                         if p[0] == "rep"}}
    via_interior = {b for (a, b) in via_edges} - dust
    no_rep: Set[P3] = set(feed_cells) | {src} | via_interior | riser_inputs

    # undirected dust adjacency + directed via edges
    adj: Dict[P3, List[P3]] = {}
    for c in dust:
        adj.setdefault(c, [])
    for c in dust:
        for dx, dy, dz in H3:
            q = (c[0] + dx, c[1] + dy, c[2] + dz)
            if q in dust:
                adj[c].append(q)
    for (a, b) in via_edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, [])

    # BFS orientation from src
    parent: Dict[P3, Optional[P3]] = {src: None}
    children: Dict[P3, List[P3]] = {}
    order: List[P3] = [src]
    dq = deque([src])
    while dq:
        u = dq.popleft()
        for v in adj.get(u, []):
            if v in parent:
                continue
            parent[v] = u
            children.setdefault(u, []).append(v)
            order.append(v)
            dq.append(v)

    powers: Dict[P3, int] = {src: 15}
    run: Dict[P3, int] = {src: 0}
    reps: List[Tuple[P3, str]] = []

    for u in order:
        p = powers.get(u, 0)
        if p < 1:
            continue
        ch = children.get(u, [])
        # straight cell: one child and grandparent->u->child collinear
        gp = parent.get(u)
        straight = None
        if len(ch) == 1 and gp is not None:
            v = ch[0]
            fin = (u[0] - gp[0], u[1] - gp[1], u[2] - gp[2])
            fout = (v[0] - u[0], v[1] - u[1], v[2] - u[2])
            fin2 = (fin[0], fin[2])
            if fin == fout and fin2 in FLOW_FACING:
                straight = FLOW_FACING[fin2]
        for v in ch:
            if v in via_map.get(u, ()):
                if _regen_edge((u, v)):
                    powers[v] = 15 if p >= 1 else 0
                    run[v] = 0
                else:
                    powers[v] = p - 1
                    run[v] = run[u] + 1
                continue
            # plain dust step
            if u != src and u in dust and u not in no_rep and \
                    straight is not None and \
                    run[u] + 1 >= MAX_RUN_REP:
                reps.append((u, straight))
                powers[v] = 15
                run[v] = 0
            else:
                powers[v] = p - 1
                run[v] = run[u] + 1
    return powers, reps


def feed_powers(net: str, ps: List[tuple], src: P3,
                sinks: List[P3]) -> Dict[P3, int]:
    """Power at every sink's west feed cell, under the same insertion model."""
    feeds = {(k[0] - 1, src[1], k[2]) for k in sinks}
    powers, _ = flow_model(net, ps, src, feeds)
    return {f: powers.get(f, 0) for f in feeds}


def insert(net: str, ps: List[tuple], src: P3, sinks: List[P3],
           wires: Set[P3], repeaters: List[Tuple[P3, str]]) -> Dict[P3, int]:
    """Materialize-side entry: compute powers, move inserted cells from wires
    to repeaters. Returns the final feed powers."""
    feeds = {(k[0] - 1, src[1], k[2]) for k in sinks}
    powers, reps = flow_model(net, ps, src, feeds)
    for (pos, facing) in reps:
        if pos in wires:
            wires.discard(pos)
        repeaters.append((pos, facing))
    return {f: powers.get(f, 0) for f in feeds}
