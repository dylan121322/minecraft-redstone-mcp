"""
via_gadget.py — the VERIFIED via gadgets as reusable geometry generators, with
their exact footprint (for the router to reserve). All MCHPRS-verified
(test_via_pin T2: full chain 2/2, non-inverting, default-0, reliable).

A via connects a y0 signal to a trunk layer (y = base + 2*L) and back. We use
repeater-risers (NOT standing-torch towers — those default-lit to 1 and caused
stuck-high). Risers spread in +x, one x-step per y-level.

Emit primitives (return list of (x,y,z,block) + occupied (x,y,z) cells):

  rise(x, z, y0, y_top):  climb from y0 dust at x to a dust at (x_out, y_top).
    Pattern per the verified T2:
      (x,   y0)   dust  (input, already placed by caller as the pin feed)
      (x+1, y0)   repeater[facing=west]  (drives east, strong)
      (x+2, y0)   block ; (x+2, y0+1) dust        <- climb 1
      (x+3, y0+1) block ; (x+3, y0+2) dust        <- climb 2
      ... each further level: (x+k, prev_y) block ; (x+k, prev_y+1) dust
    Reaches y_top at x_out = x + 2 + (y_top - y0).  Returns x_out.

  drop(x, z, y_top, y0): descend from a trunk dust at (x, y_top) down to y0 at
    x_out, +x staircase (see-below, no repeater, non-inverting):
      (x,   y_top)  dust  (trunk, already there)
      (x+1, y_top-1) block ; (x+1, y_top-1... ) ... each +x drops one level
    Reaches y0 at x_out = x + (y_top - y0).

These footprints tell the router how many +x cells to reserve for each via.
"""

W = "minecraft:redstone_wire"; S = "minecraft:stone"
def rep_w(): return "minecraft:repeater[facing=west,delay=1]"


def rise_cells(x, z, y0, y_top):
    """Repeater-riser from (x,y0) to (x_out,y_top). Returns (placements, x_out).
    placements: list of (wx,wy,wz,block). Occupies x..x_out at various y."""
    p = []
    # repeater at x+1 (drives east from the y0 dust at x)
    p.append((x+1, y0, z, rep_w()))
    # first climb block+dust at x+2 (y0 -> y0+1)
    cx = x+2; cy = y0
    p.append((cx, cy, z, S))
    p.append((cx, cy+1, z, W))
    cy += 1
    # continue climbing one level per +x until y_top, inserting a repeater
    # refresh every ~12 climbed levels so the signal never decays below 1 on a
    # tall via (a diagonal dust climb loses 1 strength per level; 29-layer alu1
    # would otherwise decay to 0). The refresh is a flat 2-cell landing at the
    # current height: dust -> repeater -> resume climbing.
    since_refresh = 1
    while cy < y_top:
        if since_refresh >= 10:
            # flat refresh at height cy: extend +x with a repeater on a support
            cx += 1
            p.append((cx, cy-1, z, S)); p.append((cx, cy, z, rep_w()))
            cx += 1
            p.append((cx, cy-1, z, S)); p.append((cx, cy, z, W))
            since_refresh = 0
        cx += 1
        p.append((cx, cy, z, S))
        p.append((cx, cy+1, z, W))
        cy += 1
        since_refresh += 1
    return p, cx  # dust now at (cx, y_top, z)


def drop_cells(x, z, y_top, y0):
    """+x staircase descent from (x,y_top) to (x_out,y0). Returns (placements,x_out).
    Each +x step drops one Y-level: at (cx, cy) place dust on a block at (cx,cy-1);
    the previous-higher dust connects DOWN to it (see-below rule). Continue until
    the dust sits at y0 on the floor. NO extra final dust (that overwrote the last
    step's block at the same cell — the drop-segment break)."""
    # Descend one Y-level per +x step. At target y, the dust sits at (cx, y) on a
    # support block at (cx, y-1); the previous-higher dust at (cx-1, y+1) connects
    # DOWN to it (see-below). Continue to y0 (dust on the floor slab, no extra
    # support). Every intermediate level MUST get a dust — skipping one (the old
    # cy>y0+1 bound jumped y2->y0 with no y1 dust) breaks the chain.
    p = []
    cx = x; cy = y_top
    since = 0
    while cy > y0:
        if since >= 10 and cy > y0 + 1:
            # flat refresh landing at current height before continuing to drop.
            # A descending dust chain loses 1/step; a deep drop (alu1 ~29 layers)
            # would decay to 0 without this. Repeater re-drives to 15. delay is
            # harmless for combinational alu1 (settles given enough ticks).
            cx += 1
            p.append((cx, cy-1, z, S)); p.append((cx, cy, z, rep_w()))
            cx += 1
            p.append((cx, cy-1, z, S)); p.append((cx, cy, z, W))
            since = 0
        cx += 1
        cy -= 1
        if cy > y0:
            p.append((cx, cy-1, z, S))   # support under this step's dust
        p.append((cx, cy, z, W))         # dust at each descending level (incl y0)
        since += 1
    return p, cx


if __name__ == "__main__":
    # self-check footprint sizes
    pr, xo = rise_cells(0, 0, 0, 10)
    print(f"rise y0->y10: x_out={xo} (width {xo-0}), {len(pr)} blocks")
    pd, xo2 = drop_cells(0, 0, 10, 0)
    print(f"drop y10->y0: x_out={xo2} (width {xo2-0}), {len(pd)} blocks")
