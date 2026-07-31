"""
test_sink_delivery.py — reproduce the module's sink-delivery geometry in a TINY
world, where a failure is diagnosable in seconds instead of minutes.

Context: the global chain works end to end in test_trunk_e2e, yet inside a real
module every sink reads a constant value independent of the source — the signature
of an odd torch count (the tower then inverts and self-drives). Eight rounds of
edits inside the 30k-block module did not settle it, so the exact same delivery is
rebuilt here in isolation, with the parameters the module actually uses:

    shaft at pin_x - 3, torch column at pin_x - 2, feed cell at pin_x - 1
    rotations from the verified set, side=(1,0)

For each rotation it reports the torch count, whether anything overwrote a torch,
and whether the sink responds to the source.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import down_tower_cells_dir

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"

ROTS = [((0, 1), (1, 0)), ((0, -1), (1, 0)),
        ((1, 0), (0, 1)), ((1, 0), (0, -1))]


def run(arm, side, drive, trunk_y=9, pin_x=20, z=4, feed_run=True):
    """Trunk dust arrives at the shaft column; tower drops into the feed cell."""
    sc = nuc.Schematic.create(f"sd_{arm}_{side}_{drive}")
    B = sc.set_block_from_string
    base = 0
    for x in range(-4, pin_x + 8):
        for zz in range(-4, z + 8):
            B(x, base - 1, zz, S)

    fx = pin_x - 3
    feed = pin_x - 1
    # drive the trunk dust that feeds the shaft: RB -> dust -> repeater -> dust
    for x in range(fx - 6, fx - 3):
        B(x, trunk_y - 1, z, S)
    B(fx - 6, trunk_y, z, RB if drive else "minecraft:air")
    B(fx - 5, trunk_y, z, W)
    B(fx - 4, trunk_y, z, repw())
    for x in range(fx - 3, fx + 1):
        B(x, trunk_y - 1, z, S)
        B(x, trunk_y, z, W)

    # parity bridge, then the tower
    dn_from = trunk_y
    if (dn_from - base) % 2:
        B(fx, dn_from - 2, z, S)
        B(fx, dn_from - 1, z, W)
        dn_from -= 1
    cells, _foot = down_tower_cells_dir(fx, z, dn_from, base, side=side, arm=arm)
    torches = [(x, y, zz) for (x, y, zz, b) in cells if "torch" in b]
    for (x, y, zz, b) in cells:
        B(x, y, zz, b)
    # feed run east into the pin, starting one column over so the tower's last
    # torch (which can land on the shaft column at y=base) is not overwritten
    if feed_run:
        for x in range(fx + 1, feed + 1):
            B(x, base, z, W)
    B(pin_x, base, z, repw())          # the gate input pin
    B(pin_x + 1, base, z, W)           # pin output

    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(60)
    return (len(torches),
            w.get_redstone_power(feed, base, z),
            w.get_redstone_power(pin_x + 1, base, z),
            torches)


if __name__ == "__main__":
    print("=== sink delivery, module parameters, per rotation ===")
    for arm, side in ROTS:
        n1, f1, o1, tor = run(arm, side, 1)
        n0, f0, o0, _ = run(arm, side, 0)
        parity = "even" if n1 % 2 == 0 else "ODD (inverts)"
        responds = f1 != f0
        print(f"  arm={arm} side={side}: torches={n1} ({parity})")
        print(f"     drive1 feed={f1:2d} pin_out={o1:2d} | "
              f"drive0 feed={f0:2d} pin_out={o0:2d}   "
              f"{'RESPONDS' if responds else 'CONSTANT'}")
        low = [t for t in tor if t[1] == 0]
        if low:
            print(f"     torches at y=0 (overwritable by a feed run): {low}")
