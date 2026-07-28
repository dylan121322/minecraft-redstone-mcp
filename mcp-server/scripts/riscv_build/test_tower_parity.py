"""
test_tower_parity.py — solve the torch-tower PARITY problem for the source rise.

A torch tower of n torches climbs +2n in Y and inverts n times. To reach an
ODD trunk layer (world-y = 2*odd), n = trunk_layer is odd => the tower INVERTS
the signal => logic bug. We need a NON-inverting rise to ANY layer.

Solution to verify: make the tower always use an EVEN torch count by choosing
n_torches = trunk_layer if even, else trunk_layer+1 (climb ONE extra pair to
y_hi+2), then bring the signal back DOWN 2 to the trunk with a tiny 1-level dust
step. But down-1 needs footprint. Simpler: put ONE extra inverting wall-torch at
the BASE (y0 plane, costs 1 horizontal cell) so total inversions = n+1. Choose
so total is even.

Cleanest: parametrize the tower by TARGET y_hi and desired polarity, and insert
a base pre-inverter iff parity is wrong. Verify BOTH parities land non-inverting.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def rep_w(): return "minecraft:repeater[facing=west,delay=1]"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def rise_to_layer(B, wx, wz, base_y, trunk_layer, drive_from_west=True):
    """Non-inverting 1x1(+base) rise from y0 to trunk world-y = base_y+2*trunk_layer.
    n_torches = trunk_layer. If trunk_layer is ODD, prepend a base wall-torch
    pre-inverter (occupies (wx-1..) at y0) so total inversions = trunk_layer+1 (even).
    Returns the world-y of the top trunk dust."""
    y_hi = base_y + 2 * trunk_layer
    n = trunk_layer
    if n % 2 == 1:
        # base pre-inverter: the incoming source dust (from west) drives a block;
        # a wall torch on it re-inverts, and THAT feeds block0. Net inversions
        # become n+1 (even) => non-inverting overall.
        # incoming dust at (wx-2, y0) -> block (wx-1,y0) -> wall torch on its east
        # face at (wx, y0)? torch must feed block0 at (wx,y0). Use:
        #   src dust (wx-2) -> block0feed... implement as: block at (wx-1),
        #   wall torch facing west on (wx-1)'s ... simpler: standing torch trick.
        # Pre-inverter as a 1-tall: block at (wx-1,base_y) fed by src dust to its
        # west; wall torch on EAST face (wx, base_y) reads it and powers block0.
        B(wx - 1, base_y, wz, S)                       # feed block (src drives from west)
        B(wx, base_y, wz, wt("east"))                  # pre-inverter reads feed block
        B(wx, base_y - 0, wz, wt("east"))
        # torch powers block above it; put block0 above the torch
        B(wx, base_y + 1, wz, S)                       # block0 (powered by pre-inv torch)
        y = base_y + 1
    else:
        B(wx, base_y, wz, S)                           # block0 driven directly from west
        y = base_y
    # climb n torches from y
    for _ in range(n):
        B(wx, y + 1, wz, TORCH)
        B(wx, y + 2, wz, S)
        y += 2
    # trunk dust on top block (at y_hi ... account for the +1 base shift)
    B(wx, y + 1, wz, W)
    return y + 1


def test_parity(trunk_layer, drive):
    sc = nuc.Schematic.create(f"p{trunk_layer}_{drive}"); B = sc.set_block_from_string
    flr(B, -8, 6, -2, 4)
    wx, wz, base_y = 2, 1, 0
    # source feed from the west at y0
    B(wx - 3, base_y, wz, RB if drive else "minecraft:air")
    B(wx - 2, base_y, wz, W)
    if trunk_layer % 2 == 1:
        # src dust must reach the pre-inverter feed block at (wx-1). extend dust.
        pass  # (wx-2) dust is adjacent to (wx-1) block below? need dust at wx-2 feeding block wx-1
    top_y = rise_to_layer(B, wx, wz, base_y, trunk_layer)
    B(wx + 1, top_y, wz, LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(50)
    p = w.get_redstone_power(wx, top_y, wz)
    return p, top_y


if __name__ == "__main__":
    print("=== rise_to_layer: NON-inverting to ANY layer (even & odd) ===")
    print("expect: drive=1 -> top power>0 ; drive=0 -> top power=0")
    for tl in (1, 2, 3, 4, 5, 6):
        p1, ty1 = test_parity(tl, 1)
        p0, ty0 = test_parity(tl, 0)
        par = "ODD" if tl % 2 else "EVEN"
        ok = (p1 > 0 and p0 == 0)
        print(f"  layer={tl}({par}) y_top={ty1}: drive1->pow={p1} drive0->pow={p0}  {'OK' if ok else 'FAIL'}")
