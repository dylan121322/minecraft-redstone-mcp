"""
test_bridge_gadget.py — the C-plan BRIDGE gadget: y0 -> UP (1x1 torch tower,
even torches, non-inverting) -> cross on a high plane -> DOWN (short staircase)
-> y0. Used to hop a net's dust OVER a blocking net without the wide lateral
climb/descent that caused the 60 shorts.

Bridge only needs to clear ONE obstacle row, so the cross plane can be y4 (2
torches up = non-inverting) and the descent is a short 4-cell staircase. The UP
tower is 1x1 (packs tight); the DOWN staircase spans 4 in x (acceptable — it's
one obstacle, not a deep trunk).

Verify: drive y0 west feed, hop up 2-torch tower to y4, run a few cells on y4,
descend to y0, read. Non-inverting, drive0 not stuck-high.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def rep_w(): return "minecraft:repeater[facing=west,delay=1]"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def bridge(B, sx, sz, base_y, cross_len=4):
    """y0 dust at (sx-1) drives a 2-torch tower at (sx) up to y4 (non-inverting),
    cross_len cells east on y4, then a 4-step +x staircase down to y0.
    Returns the landing (x_out, base_y, sz)."""
    # UP tower: repeater feed at sx-1, block0 at sx, 2 torches -> top dust y=base+5
    B(sx - 1, base_y, sz, rep_w())
    B(sx, base_y, sz, S)
    y = base_y
    for _ in range(2):                        # 2 torches => non-inverting, +4 Y
        B(sx, y + 1, sz, TORCH)
        B(sx, y + 2, sz, S)
        y += 2
    top_y = y + 1                             # dust at base_y+5
    B(sx, top_y, sz, W)
    # CROSS east on y=top_y
    cx = sx
    for _ in range(cross_len):
        cx += 1
        B(cx, top_y - 1, sz, S)
        B(cx, top_y, sz, W)
    # DESCEND +x staircase from (cx, top_y) to y0
    dy = top_y
    while dy > base_y:
        cx += 1
        dy -= 1
        if dy > base_y:
            B(cx, dy - 1, sz, S)
        B(cx, dy, sz, W)
    return (cx, base_y, sz)


def test(cross_len, drive):
    sc = nuc.Schematic.create(f"br{cross_len}_{drive}"); B = sc.set_block_from_string
    flr(B, -6, 40, -2, 4)
    sx, sz, base_y = 2, 1, 0
    B(sx - 3, base_y, sz, RB if drive else "minecraft:air")
    B(sx - 2, base_y, sz, W)                  # feeds repeater at sx-1
    land = bridge(B, sx, sz, base_y, cross_len)
    B(land[0] + 1, land[1], land[2], LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(60)
    return w.get_redstone_power(*land)


if __name__ == "__main__":
    print("=== bridge up(2-torch,y4)-over-down, non-inverting ===")
    allok = True
    for cl in (2, 4, 8, 16):
        p1 = test(cl, 1); p0 = test(cl, 0)
        ok = (p1 > 0 and p0 == 0)
        allok &= ok
        print(f"  cross_len={cl:2d}: drive1->{p1} drive0->{p0}  {'OK' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")
