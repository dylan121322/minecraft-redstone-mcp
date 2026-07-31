"""
test_trunk_box.py — verify TrunkBox alone, then TrunkBox + DeliveryBox end to end.

The delivery boxes already pass sealed and hostile; the global chain does not,
because its upstream half is hand-joined. TrunkBox packages that half the same way,
so the same two questions decide whether it helps:

  1. does it carry a signal from `in` to `out`, non-inverting, over realistic
     distances (a long run and a long leg)?
  2. is it immune to hostile geometry pressed against the shell?

Then the two boxes are chained — two modules, one boundary — which is the whole
point: ten hand-checked boundaries collapse into one.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from trunk_box import TrunkBox
from delivery_box import DeliveryBox, TowerBox

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def world_for(boxes, drive, hostile=False, base_y=0, ticks=120):
    sc = nuc.Schematic.create("tb")
    B = sc.set_block_from_string
    xs, ys, zs = [], [], []
    for b in boxes:
        (x0, y0, z0), (x1, y1, z1) = b.extent
        xs += [x0, x1]; ys += [y0, y1]; zs += [z0, z1]
    fx0, fx1 = min(xs) - 8, max(xs) + 10
    fz0, fz1 = min(zs) - 6, max(zs) + 8
    for x in range(fx0, fx1 + 1):
        for z in range(fz0, fz1 + 1):
            B(x, base_y - 1, z, S)
    for b in boxes:
        for (x, y, z), blk in b.blocks.items():
            B(x, y, z, blk)

    # drive the first box's `in` from the west, the way a gate output would
    ix, iy, iz = boxes[0].in_cell
    B(ix - 2, iy, iz, RB if drive else "minecraft:air")
    B(ix - 1, iy, iz, W)

    # read the last box's `out` through a short run and a gate-style pin
    ox, oy, oz = boxes[-1].out_cell
    B(ox + 1, oy, oz, W)
    B(ox + 2, oy, oz, repw())
    B(ox + 3, oy, oz, W)

    if hostile:
        for b in boxes:
            (x0, y0, z0), (x1, y1, z1) = b.extent
            for z in (z0 - 1, z1 + 1):
                for x in range(x0, x1 + 1, 2):
                    B(x, base_y, z, W)
                    B(x, base_y, z + (1 if z > z1 else -1), RB)
            for k in range(0, min(6, max(1, y1 - base_y)), 2):
                B(x1 + 1, base_y + k, z1 + 1, S)
                B(x1 + 1, base_y + k + 1, z1 + 1, "minecraft:redstone_torch")

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return (w.get_redstone_power(*boxes[-1].out_cell),
            w.get_redstone_power(ox + 3, oy, oz))


def check(name, boxes):
    o1, p1 = world_for(boxes, 1)
    o0, _ = world_for(boxes, 0)
    h1, _ = world_for(boxes, 1, hostile=True)
    h0, _ = world_for(boxes, 0, hostile=True)
    clean = (o1 > 0 and o0 == 0)
    shield = (h1 > 0 and h0 == 0)
    print(f"  {name}")
    print(f"      clean   drive1 out={o1:2d} pin={p1:2d} | drive0 out={o0:2d}"
          f"   {'OK' if clean else 'FAIL'}")
    print(f"      hostile drive1 out={h1:2d} | drive0 out={h0:2d}"
          f"   {'SHIELDED' if shield else 'LEAKS'}")
    return clean and shield


if __name__ == "__main__":
    ok = True
    print("=== TrunkBox alone (plane must be base+4k+1) ===")
    for plane, run_to, leg_to in ((5, 40, 20), (5, 200, 60), (9, 120, 40),
                                  (13, 260, 70)):
        tb = TrunkBox(src_cell=(0, 0, 10), plane=plane,
                      run_to_x=run_to, leg_to_z=leg_to)
        ok &= check(f"trunk plane={plane} run_to={run_to} leg_to={leg_to} "
                    f"(torches={tb.torches}, vol={tb.volume()})", [tb])

    print("\n=== TrunkBox + DeliveryBox: two modules, ONE boundary ===")
    for plane in (5, 9):
        tb = TrunkBox(src_cell=(0, 0, 10), plane=plane, run_to_x=150, leg_to_z=40)
        ox, oy, oz = tb.out_cell
        drop = plane                      # box descends from the trunk plane to base
        if drop <= 8:
            db = DeliveryBox(anchor=(ox + 2, oy, oz), drop=drop)
        else:
            db = TowerBox(anchor=(ox + 2, oy, oz), drop=drop)
        # bridge the single boundary between the two shells
        bridge = {}
        for x in range(ox + 1, db.in_cell[0]):
            bridge[(x, oy, oz)] = W
            bridge[(x, oy - 1, oz)] = S
        db.blocks.update(bridge)
        ok &= check(f"chain plane={plane} ({'stairs' if drop <= 8 else 'tower'})",
                    [tb, db])

    print(f"\n  => {'ALL OK' if ok else 'SOME FAIL'}")
