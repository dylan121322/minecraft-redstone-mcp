"""
test_two_boxes.py — verify BOTH delivery modules behind one contract.

The router should be free to choose per sink, so both kinds must satisfy the same
promise: non-inverting from `in` to `out`, and immune to hostile geometry pressed
against the shell.

  STAIRS  simple, unconditionally non-inverting, but loses a level per level
          dropped — expected to work only for shallow drops.
  TOWER   regenerates at each rung so depth is free electrically, but inverts, so
          it carries its own compensating inverter inside the shell.

Reported per kind and depth, judged strictly in both directions.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from delivery_box import DeliveryBox, TowerBox, delivery_for_sink

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def exercise(box, drive, hostile=False, base_y=0, ticks=90):
    sc = nuc.Schematic.create("two")
    B = sc.set_block_from_string
    (x0, y0, z0), (x1, y1, z1) = box.extent
    for x in range(x0 - 10, x1 + 12):
        for z in range(z0 - 6, z1 + 8):
            B(x, base_y - 1, z, S)
    for (x, y, z), b in box.blocks.items():
        B(x, y, z, b)

    ix, iy, iz = box.in_cell
    for x in range(ix - 4, ix):
        B(x, iy - 1, iz, S)
    B(ix - 4, iy, iz, RB if drive else "minecraft:air")
    B(ix - 3, iy, iz, W)
    B(ix - 2, iy, iz, repw())
    B(ix - 1, iy, iz, W)

    ox, oy, oz = box.out_cell
    B(ox + 1, oy, oz, W)
    B(ox + 2, oy, oz, repw())
    B(ox + 3, oy, oz, W)

    if hostile:
        for z in (z0 - 1, z1 + 1):
            for x in range(x0, x1 + 1):
                B(x, base_y, z, W)
                B(x - 1, base_y, z, RB)
        lx = x1 + 1
        for k in range(0, min(8, max(1, y1 - base_y)), 2):
            B(lx, base_y + k, z1 + 1, S)
            B(lx, base_y + k + 1, z1 + 1, "minecraft:redstone_torch")

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return w.get_redstone_power(*box.out_cell), w.get_redstone_power(ox + 3, oy, oz)


def check(name, box):
    o1, p1 = exercise(box, 1)
    o0, _p0 = exercise(box, 0)
    h1, _ = exercise(box, 1, hostile=True)
    h0, _ = exercise(box, 0, hostile=True)
    clean = (o1 > 0 and o0 == 0)
    shield = (h1 > 0 and h0 == 0)
    print(f"  {name:22s} vol={box.volume():5d} in={box.in_cell} out={box.out_cell}")
    print(f"      clean  drive1 out={o1:2d} pin={p1:2d} | drive0 out={o0:2d}"
          f"   {'OK' if clean else 'FAIL'}")
    print(f"      hostile drive1 out={h1:2d} | drive0 out={h0:2d}"
          f"   {'SHIELDED' if shield else 'LEAKS'}")
    return clean and shield


if __name__ == "__main__":
    print("=== STAIRS box ===")
    ok = True
    for drop in (2, 4, 8, 12, 20):
        ok &= check(f"stairs drop={drop}", DeliveryBox(anchor=(30, drop, 5),
                                                      drop=drop))
    print("\n=== TOWER box (depth-independent, inverter inside) ===")
    for drop in (4, 8, 12, 20, 28):
        try:
            ok &= check(f"tower drop={drop}", TowerBox(anchor=(30, drop, 5),
                                                       drop=drop))
        except Exception as e:
            print(f"  tower drop={drop}: {type(e).__name__}: {e}")
            ok = False

    print("\n=== chooser ===")
    for drop in (4, 8, 12, 20):
        b, kind = delivery_for_sink((225, 0), trunk_y=drop, base_y=0)
        print(f"  trunk_y={drop:2d} -> {kind:6s} in={b.in_cell} out={b.out_cell}"
              f"  (out should be 2 west of the pin at x=223)")
    print(f"\n  => {'ALL OK' if ok else 'SOME FAIL'}")
