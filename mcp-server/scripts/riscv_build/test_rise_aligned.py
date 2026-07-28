"""
test_rise_aligned.py — rise whose TOP DUST lands EXACTLY on trunk_wy=2*layer
(even), so it joins the flat trunk plane at the same Y. This fixes the off-by-one
between the 'block+dust-above' tower (dust at odd Y) and the even-layer trunk.

Geometry: block0@base_y, then (torch, block) pairs. After n torches the top
BLOCK is at base_y+2n. Put the TRUNK DUST on TOP of that block => dust at
base_y+2n+1 (ODD). To land dust at EVEN 2*layer, we instead make the LAST step a
dust (not a block): ... block@(2n-2)+torch@(2n-1)+block@(2n) then dust@(2n) is
impossible (dust needs a block under it, and 2n block is there) => dust sits at
2n+1. So a standing-torch tower's readable dust is ALWAYS at odd Y.

Resolution: define trunk_wy = base_y + 2*layer + 1 (odd) as the ACTUAL trunk
plane. i.e. the trunk plane sits at odd world-Y (block supports at even Y). The
router's layer index maps to world-Y = 2*layer, but the emit places the trunk
DUST one higher, at 2*layer+1, uniformly for ALL cells of the net (trunk run,
source top, sink launch). As long as EVERY dust of a net is at the same odd Y and
supports at even Y below, H/V isolation (2-Y gap) still holds between different
nets' trunks (they're at 2*layer_a+1 vs 2*layer_b+1, gap = 2*|la-lb| >= 2).

So: emit_rise returns top dust at base_y+2n+1; n=layer (even => non-inverting).
Trunk plane Y for the whole net = base_y+2*trunk_layer+1. Verify non-inverting
AND that the returned dust is a normal dust that can extend horizontally (trunk).
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


def emit_rise(B, wx, wz, base_y, layer):
    """n=layer torches (EVEN => non-inverting). Top dust at base_y+2*layer+1.
    Caller drives a repeater feed from the west at (wx-1,base_y)."""
    B(wx - 1, base_y, wz, rep_w())
    B(wx, base_y, wz, S)
    y = base_y
    for _ in range(layer):
        B(wx, y + 1, wz, TORCH)
        B(wx, y + 2, wz, S)
        y += 2
    top_dust_y = y + 1                       # dust on top of final block
    B(wx, top_dust_y, wz, W)
    return top_dust_y


def test_rise_then_trunk(layer, drive, trunk_len=6):
    """Rise, then run a horizontal trunk of trunk_len dust at the top Y, confirm
    the signal reaches the far end (tests that the top dust is a real conductor)."""
    sc = nuc.Schematic.create(f"a{layer}_{drive}"); B = sc.set_block_from_string
    flr(B, -8, 40, -2, 4)
    wx, wz, base_y = 2, 1, 0
    B(wx - 3, base_y, wz, RB if drive else "minecraft:air")
    B(wx - 2, base_y, wz, W)                 # feeds the repeater at wx-1
    ty = emit_rise(B, wx, wz, base_y, layer)
    # trunk run east on y=ty, support below at ty-1
    for i in range(1, trunk_len + 1):
        B(wx + i, ty - 1, wz, S)
        B(wx + i, ty, wz, W)
    far = (wx + trunk_len, ty, wz)
    B(far[0] + 1, far[1], far[2], LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(60)
    return w.get_redstone_power(*far), ty


if __name__ == "__main__":
    print("=== even-layer rise + trunk run, top dust at 2*layer+1 (odd Y plane) ===")
    allok = True
    for layer in (2, 4, 6, 8, 10, 20):
        p1, ty = test_rise_then_trunk(layer, 1)
        p0, _ = test_rise_then_trunk(layer, 0)
        ok = (p1 > 0 and p0 == 0)
        allok &= ok
        print(f"  layer={layer:2d} trunkY={ty}: drive1->far={p1} drive0->far={p0}  {'OK' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")
