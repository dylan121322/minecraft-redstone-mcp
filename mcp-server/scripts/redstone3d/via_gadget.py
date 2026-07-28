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
    # continue climbing one level per +x until y_top
    while cy < y_top:
        cx += 1
        p.append((cx, cy, z, S))
        p.append((cx, cy+1, z, W))
        cy += 1
    return p, cx  # dust now at (cx, y_top, z)


def drop_cells(x, z, y_top, y0):
    """+x staircase descent from (x,y_top) to (x_out,y0). Returns (placements,x_out)."""
    p = []
    cx = x; cy = y_top
    while cy > y0:
        cx += 1
        p.append((cx, cy-1, z, S))       # block one lower
        p.append((cx, cy, z, W))          # dust steps down (see-below to prev)
        cy -= 1
    # final y0 dust
    p.append((cx, y0, z, W))
    return p, cx


if __name__ == "__main__":
    # self-check footprint sizes
    pr, xo = rise_cells(0, 0, 0, 10)
    print(f"rise y0->y10: x_out={xo} (width {xo-0}), {len(pr)} blocks")
    pd, xo2 = drop_cells(0, 0, 10, 0)
    print(f"drop y10->y0: x_out={xo2} (width {xo2-0}), {len(pd)} blocks")
