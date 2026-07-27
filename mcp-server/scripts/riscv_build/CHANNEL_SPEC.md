# 2-Layer Manhattan Channel Router — Verified Spec

Goal: route a columnar gate placement into redstone with ZERO adjacency shorts,
correct-by-construction, using a 2-layer Manhattan discipline. All physics below
is VERIFIED in MCHPRS (nucleation) and/or in-game.

## Coordinate / layer model (base_y = b, from placement.bounds[0][1])
- y=b    : cell bodies + pins (placer output). Input pins are `repeater[facing=west]`
           on a cell's WEST edge; they read their WEST neighbor (px-1) and drive east.
           Output pins are `redstone_wire` on the EAST edge.
- y=b+2  : H-LAYER — horizontal (X-direction) dust runs ONLY. Each dust needs a
           solid support at y=b+1 below it.
- y=b+4  : V-LAYER — vertical (Z-direction) dust runs ONLY. Support at y=b+3.

## Verified primitives (typed placements: ("dust",x,y,z)/("rep",x,y,z,facing)/("block"/"support",x,y,z))

### Climb y0 -> y2 (needs repeater priming; flow +x). start at output-pin x=sx,z=sz:
  ("rep", sx+1, b, sz, "west")
  ("block", sx+2, b, sz)   ("dust", sx+2, b+1, sz)
  ("block", sx+3, b+1, sz) ("dust", sx+3, b+2, sz)   # y2 dust lands at (sx+3, sz)

### Climb y2 -> y4 (flow +x), given y2 dust already at (x, sz):
  ("block", x+1, b+2, sz) ("dust", x+1, b+3, sz)
  ("block", x+2, b+3, sz) ("dust", x+2, b+4, sz)     # y4 dust lands at (x+2, sz)

### Horizontal run on y2 (row z), x from a..bx inclusive:
  for each x: ("support", x, b+1, z) ("dust", x, b+2, z)

### Vertical run on y4 (col x), z from a..bz inclusive:
  for each z: ("support", x, b+3, z) ("dust", x, b+4, z)

### Descend y4 -> y0 (NO repeater; +x staircase, "see-below" rule). y4 dust at (x0,pz):
  ("block", x0+1, b+2, pz) ("dust", x0+1, b+3, pz)
  ("block", x0+2, b+1, pz) ("dust", x0+2, b+2, pz)
  ("block", x0+3, b,   pz) ("dust", x0+3, b+1, pz)
  ("dust",  x0+4, b, pz)                              # y0 dust lands at (x0+4, pz)
  => to feed a west-facing pin at (px,0,pz), set x0 = px-5 so landing = (px-1, pz).

## Isolation rules (MCHPRS-measured, test_hv_layers.py)
- H(y2) of net A crossing V(y4) of net B at same (x,z) with solid y3 block between = ISOLATED (Q2 4/4).
- Parallel same-layer same-direction dust need center-to-center separation >= 2.
- H and V of DIFFERENT nets cross freely (different y-layer). So the ONLY short
  risk is two nets' segments on the SAME layer running adjacent (<2 apart) in the
  SAME direction, OR two nets' vias/climbs adjacent. Track assignment must ensure:
  * each net's H trunk on a UNIQUE y2 row (z), rows spaced >= 2
  * each net's V segments on UNIQUE y4 columns (x), columns spaced >= 2
  * climbs/descents (which touch y0/y1/y2/y3) don't sit within Chebyshev 2 of a
    foreign net's y0/y2 dust.

## Correct routing recipe per net (source -> many sinks, DAG, sinks east of source)
1. Climb source pin y0->y2 (+x). Now y2 dust at (sx+3, sz).
2. H-run on y2 along the net's RESERVED row R (z=R). To get from sz to R (a Z
   move) you must use y4: climb y2->y4, V-run sz->R, descend back to y2 — OR,
   simpler, reserve R = sz is impossible (sz is a cell row). 
   RECOMMENDED: keep the H trunk at a reserved row R north of the field. Reach it
   by: climb y2->y4 right after step 1, V-run (sz -> R) on a reserved column,
   then the net travels on y4 V-segments and y2 H-segments as needed.
3. For each sink (px,pz): deliver signal to a y4 dust at (px-5, pz) on the net's
   reserved column, then descend to land y0 at (px-1,pz) feeding the pin.

Because H and V of different nets are on different layers, the classic 2-layer
channel router applies: assign H-tracks (rows) and V-tracks (columns) so same-
layer segments never overlap/adjacent. With <=40 nets and generous spacing this
always succeeds.

## GLOBAL-GRID SCHEME (correct-by-construction, use THIS — heuristics proven not to converge)

The failure of all prior attempts: signals routed OUTSIDE the cell field then
"dive back" into pins, and the dive-backs / risers collide. The fix is a rigid
global grid where EVERY net owns unique tracks, so overlap is impossible.

Give each net i (i = 0..N-1) TWO dedicated tracks:
  - H-ROW  Ri on y=2 at z = Z_TOP + 2*i        (Z_TOP north of the cell field)
  - V-COL  Ci on y=4 at x = X_EAST + 2*i        (X_EAST east of the cell field)
Both spaced 2 => no two nets' H-rows adjacent, no two nets' V-cols adjacent.
H(y2) and V(y4) of different nets cross freely (verified isolated, Q2).

Per net route (all turns are via layer-changes, never same-layer corners):
  1. SOURCE PICKUP: at the driver output pin (sx,0,sz), climb y0->y2. Run H on
     y2 EAST along z=sz? No — sz is a cell row. Instead climb immediately to the
     net's own H-row Ri: climb y0->y2 at source, then a SHORT dedicated riser to
     reach Ri. Because each net's riser is on ITS OWN Ci (unique x), risers never
     collide. Concretely: climb y0->y2->y4 at source x, V-run on y4 at the
     source's own unique riser column to z=Ri... 
  ** Cleanest formulation that removes ALL coupling: **
     a. climb source y0->y2->y4 at a per-net unique column near the source
        (source pickup column = X_WEST - 2*i, WEST of the field, unique per net).
        Reach it by a short y2 H-run on a per-net-unique row just for pickup, OR
        simpler: since sources are at distinct (sx,sz) mostly, but PIs share sx=0,
        the pickup MUST use a unique column per net — allocate from a global pool.
     b. V-run on y4 (pickup column) from sz to the net's H-row Ri.
     c. drop y4->y2 at (pickup_col, Ri); H-run EAST on Ri to the net's V-col Ci.
     d. climb y2->y4 at Ci; V-run on y4 (col Ci) covering all sink z's.
     e. per sink (px,pz): from Ci at z=pz, the signal must travel WEST on y2 to
        reach px. Drop y4->y2 at (Ci,pz)? but pz is a cell row shared by sinks of
        other nets... => the SINK APPROACH is the crux. 

  ** SINK APPROACH (the vertical-constraint problem) — solve with per-sink H-row: **
     Give EACH SINK its own dedicated y2 H-approach row Aj = Z_TOP2 + 2*j (a second
     band of rows, one per sink, north or south). Route: from Ci, V-run on y4 to
     z=Aj, drop y4->y2 at (Ci,Aj), H-run WEST on Aj (unique row, no collision) to
     x=px-3, then descend into the pin at (px-1,pz) via a y2->y0 dogleg that also
     moves z from Aj to pz. The z-move (Aj->pz) is a V-move => must be on y4:
       at (px-3, Aj) climb y2->y4, V-run y4 (col px-3, unique? px-3 shared by
       sinks in same placement col) ...
     => the sink-approach V-move column (px-3) is shared. Assign per-sink unique
     approach columns: sink j uses column (X_APPR - 2*j) in a reserved band, does
     its Aj-row H to there, V-runs to pz, then the verified descent-into-pin lands
     at (px-1,pz). The final short y0 jog (approach_col+4 .. px-1) is at row pz;
     two sinks share pz only if in the same placement column AND same z — but
     each pin has a unique (px,pz), and only its own net drives it. Different
     nets' y0 jogs at the same pz (different px) don't overlap if px differ.

  NET: allocate FOUR global unique-track pools, each spaced 2:
    - source pickup columns (y4)         : one per net
    - net trunk rows Ri (y2)             : one per net
    - net trunk columns Ci (y4)          : one per net
    - sink approach rows Aj (y2)         : one per SINK
    - sink approach columns (y4)         : one per SINK
  With unique tracks everywhere and layer-separated H/V, NO two different nets'
  segments are ever adjacent on the same layer => 0 shorts by construction. The
  layout grows (O(N) rows + O(sinks) rows, O(N+sinks) cols) but for <=29 nets /
  ~45 sinks that's fine. Correctness over compactness.

## TORCH-TOWER REFACTOR (the fix for residual shorts — verified primitive)

The 4-wide +x descent staircase creates intermediate y2/y3 dust that shorts
between different nets' descents (the 11 residual shorts). REPLACE all vertical
transmission (climb AND descent) with VERTICAL TORCH TOWERS:

  Tower climbing +y at (x,z): powered block0 (fed by a repeater to its west) then
  repeat { standing redstone_torch on top ; solid block on top of torch }. Each
  torch inverts; use an EVEN torch count for non-inverting transmission. Footprint
  is 1x1 in the plane. Verified MCHPRS (test_vertical.py V2, test_tower_iso.py):
    - drive=0 -> torch-lit pattern [1,0,1...]; drive=1 -> [0,1,0...] (per-level NOT)
    - adjacent towers of DIFFERENT nets are isolated at sep=1 (solid column blocks
      coupling) — pack towers 1 apart.
  Reliable drive: redstone_block -> wire -> repeater[facing=west] -> block0.
  (redstone_block directly on dust does NOT inject under /setblock.)

Router consequence: a net's source pickup and each sink delivery become 1x1
towers instead of 4-wide staircases. Same-placement-column sinks (pz differ by
2) get towers 2 apart in z => isolated. This removes the intermediate-dust short
class entirely AND shrinks footprint. Horizontal trunks stay on y2 (H) reserved
rows; the tower tops connect to the y2/y4 trunk via a short dust stub. Track
assignment for horizontal rows/cols is unchanged (already 0 shorts on y4).

## MINIMAL-DETOUR REWRITE (generalize + shrink — the global-grid was 12x bloated)

MEASURED PROBLEM: the global-grid router (unique far-north trunk row + far-east
trunk col per net) forces every net to detour to distant trunks then back —
alu1 used 23390 wires vs ~1915 Manhattan lower bound = 12.2x bloat; net n25
(source & sinks within x=9-26,z=2-19) was dragged to x=336,z=150 and back (33x).
This bloat wastes space AND creates huge adjacency surface = more shorts. The
user explicitly flagged "one column expanded into many" as a short source.

CORRECT ARCHITECTURE (generalized, minimal): route each net near its OWN
source→sink bounding box, shortest-path first; only detour (via a 1x1 torch
tower to another layer) where a real conflict forces it.
  - y=0 signal plane: gate cells + local dust that routes flat when clear.
  - When two nets must cross, ONE hops up via a torch tower (1x1, sep=1 isolated,
    verified) to y=2, crosses over on y=2, drops back — LOCAL detour only, not a
    trip to a global trunk.
  - Per-net A*/Lee on y=0 with HARD short-rejection (8-neighborhood + vertical);
    if blocked, allow a tower-up-over-down segment at the blockage.
  - Repeater every <=13 dust to refresh (facing = reverse of travel: +x→west,
    -x→east, +z→north, -z→south — MCHPRS-verified).
This keeps wire count near the Manhattan bound and the layout compact, which by
itself slashes the short surface. Must generalize: work for ALL modules
(Control/Mux/ALU_Control/Imm_Gen/Forwarding/ALU), not hard-coded to alu1.

## IMPLEMENTATION BASE: merge route_buildable (minimal) + torch-tower bridges

MEASURED: `route_buildable.py` BuildableRouter already routes alu1 at 1891 wires =
1.0x Manhattan (17/29 nets flat on y=0), but its `_bridge` (old lateral +x
staircase) gives 61 shorts + 2 unrouted because multiple bridges collide. The
global-grid route_channel.py is 0 shorts but 12x bloat. MERGE: keep
route_buildable's minimal flat skeleton (route()/_plane_bfs — DO NOT change the
y=0 shortest-path routing), REPLACE only `_bridge` with a torch-tower up-over-down
gadget so bridges don't collide.

Torch-tower crossing (verified: test_vertical.py/test_tower_iso.py/test_tower_route.py):
to cross over blocking nets, hop from y0 up a 1x1 torch tower to y2, run on y2
(H-layer) over the obstacle, drop back to y0 into the sink. Towers are 1x1 and
isolated at sep=1, so many bridges pack without colliding. y2 crossings over y0
are isolated (2-block gap). Repeater every <=13 dust; facing = reverse of travel
(+x→west,-x→east,+z→north,-z→south, MCHPRS-verified). Vertical torch tower up:
powered block0 (fed by repeater from west) → {standing redstone_torch on top;
block on top} repeated; even torch count = non-inverting.

## Validation
- Wire count should be within ~2-3x Manhattan lower bound (not 12x).
- Legality check: 0 shorts (8-neighborhood same-y + vertical y±1) and 0 floats
  (every y>b dust has a solid support at y-1).
- MCHPRS truth table: alu1 must hit 40/40 (ops AND/OR/ADD/XOR/SUB × a,b,cin).
- Files: placer.py (Placement), route_channel.py (target), verify_tracks_mchprs.py
  (adapt for ChannelRouter), test_descent_pin.py / test_hv_layers.py (primitives).
