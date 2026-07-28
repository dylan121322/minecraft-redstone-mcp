"""
test_via_tower.py — DEFINITIVE MCHPRS verification of the 1x1 vertical torch-tower
via that replaces the horizontal repeater-riser (which spread +1 column per level
and caused real-geometry shorts). This is the crux gadget for the emit rewrite.

Tower construction (column at (x,z), climbs +y):
  base: route dust feeds block0 (tested two drive styles below).
  repeat n times: standing redstone_torch on top of current block; solid block on
                  top of that torch.  => 2 torches climb +4 y (per torch +2 y).
  read: dust on TOP of the final block (a strongly-powered block powers the dust
        above it to 15). A redstone_lamp beside that dust confirms.

Electrics (to verify, not assume):
  drive=1 -> block0 powered -> torch1 OFF -> block1 unpow -> torch2 ON -> block2 POW
  => EVEN torch count = non-inverting; top = drive.
  drive=0 -> block0 unpow -> torch1 ON -> ... -> even block unpow => top = 0.
  Each torch REGENERATES to 15, so a deep tower does NOT decay (unlike dust climb).

MUST confirm: (1) even = non-inverting, (2) drive=0 is NOT stuck-high (the old bug),
(3) deep tower (y20) still works, (4) two adjacent towers sep=1 are isolated.
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


def build_tower(B, x, z, n_torches, base_y=0, drive=1, use_repeater=True):
    """Emit a 1x1 torch tower at (x,z) climbing n_torches torches from base_y.
    Returns (top_dust_xyz). Driven from the WEST at base_y.
    use_repeater: RB->wire->repeater(west)->block0  (strong, isolated).
    else:         RB/air->wire->wire adjacent to block0 (weak power via dust)."""
    if use_repeater:
        B(x - 3, base_y, z, RB if drive else "minecraft:air")
        B(x - 2, base_y, z, W)
        B(x - 1, base_y, z, rep_w())        # faces west, drives east into block0
    else:
        B(x - 2, base_y, z, RB if drive else "minecraft:air")
        B(x - 1, base_y, z, W)              # dust adjacent to block0 (weak power)
    B(x, base_y, z, S)                       # block0
    y = base_y
    for _ in range(n_torches):
        B(x, y + 1, z, TORCH)                # standing torch on top of current block
        B(x, y + 2, z, S)                    # block on top of torch
        y += 2
    y_top = base_y + 2 * n_torches           # final block level
    B(x, y_top + 1, z, W)                    # trunk dust ON TOP of final block
    return (x, y_top + 1, z)


def test_height(n_torches, use_repeater=True):
    """Return {drive: top_power} for a single tower of n_torches."""
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"t{n_torches}_{drive}"); B = sc.set_block_from_string
        flr(B, -6, 6, -2, 4)
        top = build_tower(B, 2, 1, n_torches, base_y=0, drive=drive,
                          use_repeater=use_repeater)
        B(top[0] + 1, top[1], top[2], LAMP)  # lamp beside the top dust
        w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(40)
        p = w.get_redstone_power(*top)
        lit = w.is_lit(top[0] + 1, top[1], top[2])
        out[drive] = (p, lit)
    return out


def test_isolation(n_torches=2):
    """Two adjacent towers (sep=1 in z): tower A driven=1, tower B driven=0.
    Confirm B's top stays 0 (no coupling from A)."""
    sc = nuc.Schematic.create("iso"); B = sc.set_block_from_string
    flr(B, -6, 8, -2, 8)
    topA = build_tower(B, 2, 2, n_torches, base_y=0, drive=1)
    topB = build_tower(B, 2, 4, n_torches, base_y=0, drive=0)  # z=4, gap z=3 between
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(40)
    return w.get_redstone_power(*topA), w.get_redstone_power(*topB)


if __name__ == "__main__":
    print("=== 1x1 torch-tower via: even=non-inverting, drive=0 must be 0 (not stuck-high) ===")
    for style, userep in [("repeater-base", True), ("dust-base", False)]:
        print(f"\n[{style}]")
        for n in (2, 4, 10):        # even -> non-inverting; y_top = 4,8,20
            r = test_height(n, use_repeater=userep)
            y_top = 2 * n + 1
            d0, d1 = r[0], r[1]
            ok = (d0[0] == 0 and d1[0] > 0)
            print(f"  n={n:2d}torches y_top={y_top:2d}: drive0->(pow={d0[0]},lit={d0[1]}) "
                  f"drive1->(pow={d1[0]},lit={d1[1]})  {'OK' if ok else 'FAIL'}")
        # parity sanity: odd should invert
        r3 = test_height(3, use_repeater=userep)
        print(f"  n= 3torches (odd,expect INVERT): drive0->pow={r3[0][0]} drive1->pow={r3[1][0]}")

    print("\n=== adjacency isolation (two towers, z sep=1 gap) ===")
    pa, pb = test_isolation(2)
    print(f"  towerA(drive1) top={pa}  towerB(drive0) top={pb}  "
          f"{'OK (isolated)' if pb == 0 and pa > 0 else 'FAIL (coupled)'}")
