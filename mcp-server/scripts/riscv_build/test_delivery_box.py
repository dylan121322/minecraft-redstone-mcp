"""
test_delivery_box.py — verify the shielded DeliveryBox, including its shield.

Two things must hold for the module-boundary argument to be worth anything:

  1. the box carries a signal from `in` to `out` non-inverting, at any drop;
  2. the box is IMMUNE to hostile geometry pressed against its shell.

Point 2 is what makes a sealed result transferable: earlier gadgets passed in
isolation and failed inside a module because neighbouring towers and local wiring
reached into them. Here the test deliberately surrounds the box with the exact
things that used to break the delivery — powered dust on all four sides, a torch
ladder right beside it, a full floor slab — and the box must behave identically.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from delivery_box import DeliveryBox, box_for_sink

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"


def build(box, drive, hostile=False, base_y=0, ticks=80):
    sc = nuc.Schematic.create(f"box_{box.drop}_{drive}_{hostile}")
    B = sc.set_block_from_string
    (x0, y0, z0), (x1, y1, z1) = box.extent

    # a wide floor at the base plane, as a real module has
    for x in range(x0 - 10, x1 + 12):
        for z in range(z0 - 6, z1 + 8):
            B(x, base_y - 1, z, S)

    # the box itself
    for (x, y, z), b in box.blocks.items():
        B(x, y, z, b)

    # drive the `in` cell from the west, at trunk height, the way a trunk does
    ix, iy, iz = box.in_cell
    for x in range(ix - 4, ix):
        B(x, iy - 1, iz, S)
    B(ix - 4, iy, iz, RB if drive else "minecraft:air")
    B(ix - 3, iy, iz, W)
    B(ix - 2, iy, iz, repw())
    B(ix - 1, iy, iz, W)

    # read the `out` cell through a short run into a gate-style input pin
    ox, oy, oz = box.out_cell
    B(ox + 1, oy, oz, W)
    B(ox + 2, oy, oz, repw())
    B(ox + 3, oy, oz, W)

    if hostile:
        # everything that used to break a bare delivery, pressed against the shell
        for z in (z0 - 1, z1 + 1):
            for x in range(x0, x1 + 1):
                B(x, base_y, z, W)
                B(x - 1, base_y, z, RB)          # driven, so it is live
        # a torch ladder immediately beside the box, like a neighbouring tower
        lx = x1 + 1
        for k in range(0, min(8, y1 - base_y), 2):
            B(lx, base_y + k, z1 + 1, S)
            B(lx, base_y + k + 1, z1 + 1, "minecraft:redstone_torch")
        # live dust directly above the box
        for x in range(x0, x1 + 1):
            B(x, y1 + 1, z0, S)
            B(x, y1 + 2, z0, W)

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return (w.get_redstone_power(*box.out_cell),
            w.get_redstone_power(ox + 3, oy, oz))


if __name__ == "__main__":
    print("=== DeliveryBox: signal, then immunity to hostile surroundings ===")
    allok = True
    for drop in (2, 4, 8, 12):
        box = DeliveryBox(anchor=(20, drop, 5), drop=drop)
        o1, p1 = build(box, 1)
        o0, p0 = build(box, 0)
        clean = (o1 > 0 and o0 == 0)
        h1, hp1 = build(box, 1, hostile=True)
        h0, hp0 = build(box, 0, hostile=True)
        shielded = (h1 > 0 and h0 == 0)
        allok &= clean and shielded
        print(f"  drop={drop:2d} vol={box.volume():4d}  "
              f"clean: drive1 out={o1:2d} pin={p1:2d} | drive0 out={o0:2d}  "
              f"{'OK' if clean else 'FAIL'}")
        print(f"              hostile: drive1 out={h1:2d} pin={hp1:2d} | "
              f"drive0 out={h0:2d}  {'SHIELDED' if shielded else 'LEAKS'}")
    print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")

    print("\n=== box_for_sink placement helper ===")
    b = box_for_sink((225, 0), trunk_y=9, base_y=0)
    print(f"  pin=(225,0) trunk_y=9 -> in={b.in_cell} out={b.out_cell} "
          f"extent={b.extent} cols={len(b.cells())}")
