"""
test_trunk_e2e.py — end-to-end check of the GLOBAL delivery chain that P1/P4 will
emit:

    y0 source dust -> repeater -> 1x1 UP tower -> straight trunk corridor
    (with refresh repeaters) -> 2x2 DOWN tower -> y0 dust feeding a west-facing
    input pin.

Every piece is individually verified already; this confirms they compose, at
lengths where an unrefreshed corridor would have decayed to nothing (the failure
that sank the earlier "long nets on the cross layer" attempt: links 16/26).

Also checks two corridors 2 apart on the same layer stay isolated, which is what
makes the corridor discipline structurally short-free.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import up_tower_cells, trunk_cells, down_tower_cells_dir

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def slab(B, x0, x1, z0, z1, y):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def build(B, drive, length, trunk_y, z):
    """Source at x=0 climbs to trunk_y, runs `length` east, drops into a pin."""
    base = 0
    # source: block -> dust -> repeater -> tower base
    B(-3, base, z, RB if drive else "minecraft:air")
    B(-2, base, z, W)
    B(-1, base, z, repw())
    up, _ = up_tower_cells(0, z, base, trunk_y - 1)  # dust lands at trunk_y
    for (x, y, zz, blk) in up:
        B(x, y, zz, blk)
    # tower's readable dust is at trunk_y; run the corridor from there
    tr, _ = trunk_cells(z, 0, length, trunk_y)
    for (x, y, zz, blk) in tr:
        B(x, y, zz, blk)
    # down tower in the pin's feed column
    feed_x = length
    # Parity bridge: the UP tower delivers its dust at 4k+1 (odd) while the DOWN
    # tower needs an even span. Step down one plain see-below level first.
    dn_from = trunk_y
    if (dn_from - base) % 2:
        B(feed_x, dn_from - 2, z, S)
        B(feed_x, dn_from - 1, z, W)
        dn_from -= 1
    dn, _ = down_tower_cells_dir(feed_x, z, dn_from, base, side=(0, 1), arm=(1, 0))
    for (x, y, zz, blk) in dn:
        B(x, y, zz, blk)
    B(feed_x, base, z, W)                       # the feed cell
    B(feed_x + 1, base, z, repw())              # the gate input pin
    B(feed_x + 2, base, z, W)                   # pin output
    return (feed_x, base, z), (feed_x + 2, base, z)


def run(drive, length, trunk_y=9, z=4):
    sc = nuc.Schematic.create(f"tr_{drive}_{length}")
    B = sc.set_block_from_string
    slab(B, -8, length + 12, -4, z + 8, -1)
    feed, pin_out = build(B, drive, length, trunk_y, z)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)
    return w.get_redstone_power(*feed), w.get_redstone_power(*pin_out)


def isolation(drive_a, drive_b, length=40, trunk_y=9, pitch=2):
    """Two corridors on the same layer, rows 2 apart."""
    sc = nuc.Schematic.create(f"iso_{drive_a}{drive_b}")
    B = sc.set_block_from_string
    slab(B, -8, length + 12, -4, 4 + pitch + 8, -1)
    fa, _ = build(B, drive_a, length, trunk_y, 4)
    fb, _ = build(B, drive_b, length, trunk_y, 4 + pitch)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)
    return w.get_redstone_power(*fa), w.get_redstone_power(*fb)


if __name__ == "__main__":
    print("=== global chain: y0 -> UP tower -> trunk -> DOWN tower -> pin ===")
    ok_all = True
    for length in (20, 60, 140, 300):
        f1, o1 = run(1, length)
        f0, o0 = run(0, length)
        ok = f1 > 0 and f0 == 0
        ok_all &= ok
        print(f"  trunk {length:3d} cells: drive1 feed={f1:2d} pin_out={o1:2d} | "
              f"drive0 feed={f0} pin_out={o0}   {'OK' if ok else 'FAIL'}")
    print(f"  => {'ALL OK' if ok_all else 'SOME FAIL'}")

    # The DOWN tower is 2x2, so its partner column sits one row over: corridors
    # spaced only 2 apart put A's tower right against B's. Sweep the pitch to find
    # the smallest spacing that stays isolated.
    for pitch in (2, 3, 4):
        print(f"\n=== two corridors on one layer, rows {pitch} apart ===")
        allok = True
        for da in (0, 1):
            for db in (0, 1):
                a, b = isolation(da, db, pitch=pitch)
                ok = (a > 0) == bool(da) and (b > 0) == bool(db)
                allok &= ok
                print(f"  driveA={da} driveB={db}: feedA={a:2d} feedB={b:2d}"
                      f"  {'ok' if ok else 'COUPLED'}")
        print(f"  => pitch {pitch}: {'ISOLATED' if allok else 'NOT USABLE'}")
