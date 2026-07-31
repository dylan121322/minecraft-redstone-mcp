"""
test_walltorch_attach.py — pin down wall-torch semantics before building the
bidirectional tower: for each `facing`, WHICH neighbouring block does the torch
attach to (i.e. which block switches it off when powered), and WHICH cells does
the lit torch power?

Method: put a single wall torch in open air on a floor, place a candidate support
block on one side at a time, and see where the torch is placeable/lit. Then power
that support (redstone_block on top of a dust above it) and check the torch goes
out. Finally map which adjacent dust cells the lit torch drives.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

DIRS = {"west": (-1, 0), "east": (1, 0), "north": (0, -1), "south": (0, 1)}


def slab(B, x0, x1, z0, z1, y):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def attach_side(facing):
    """Find which side holds the block a wall torch of this facing sits on:
    place the torch alone with a block on ONE side and see if it stays lit."""
    results = {}
    for side, (dx, dz) in DIRS.items():
        sc = nuc.Schematic.create(f"at_{facing}_{side}")
        B = sc.set_block_from_string
        slab(B, -4, 4, -4, 4, -1)
        tx, tz = 0, 0
        B(tx + dx, 0, tz + dz, S)          # candidate support
        B(tx, 0, tz, wt(facing))
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(10)
        results[side] = 1 if w.is_lit(tx, 0, tz) else 0
    return results


def switch_off(facing, side):
    """With the support on `side`, power it and confirm the torch goes out."""
    dx, dz = DIRS[side]
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"off_{facing}_{side}_{drive}")
        B = sc.set_block_from_string
        slab(B, -6, 6, -6, 6, -1)
        tx, tz = 0, 0
        sup = (tx + dx, tz + dz)
        B(sup[0], 0, sup[1], S)
        B(tx, 0, tz, wt(facing))
        # power the support block from ABOVE with a dust fed by a block
        B(sup[0], 1, sup[1], W)
        B(sup[0] + 1, 1, sup[1], RB if drive else "minecraft:air")
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(20)
        out[drive] = 1 if w.is_lit(tx, 0, tz) else 0
    return out


def powers(facing, side):
    """Which adjacent dust cells does the LIT torch drive?"""
    dx, dz = DIRS[side]
    sc = nuc.Schematic.create(f"pw_{facing}_{side}")
    B = sc.set_block_from_string
    slab(B, -6, 6, -6, 6, -1)
    tx, tz = 0, 0
    B(tx + dx, 0, tz + dz, S)
    B(tx, 0, tz, wt(facing))
    probe = {}
    for name, (qx, qz) in DIRS.items():
        if (qx, qz) == (dx, dz):
            continue
        B(tx + qx, 0, tz + qz, W)
    B(tx, 1, tz, W)                      # cell above the torch
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(20)
    for name, (qx, qz) in DIRS.items():
        if (qx, qz) == (dx, dz):
            continue
        probe[name] = w.get_redstone_power(tx + qx, 0, tz + qz)
    probe["above"] = w.get_redstone_power(tx, 1, tz)
    return probe


if __name__ == "__main__":
    print("=== which side does a wall torch attach to? (lit = placeable) ===")
    attach = {}
    for f in DIRS:
        r = attach_side(f)
        lit_sides = [s for s, v in r.items() if v]
        attach[f] = lit_sides
        print(f"  facing={f:5s}: lit with support on {lit_sides}")

    print("\n=== powering that support switches the torch OFF? ===")
    for f, sides in attach.items():
        for s in sides:
            r = switch_off(f, s)
            print(f"  facing={f:5s} support={s:5s}: drive0->lit={r[0]} drive1->lit={r[1]}"
                  f"  {'OK (inverts)' if r[0] == 1 and r[1] == 0 else 'unexpected'}")

    print("\n=== which cells does the lit torch power? ===")
    for f, sides in attach.items():
        for s in sides:
            print(f"  facing={f:5s} support={s:5s}: {powers(f, s)}")
