"""
test_rep_facing.py — nail down repeater facing semantics for all four directions.
A repeater reads from ONE side and drives the opposite. The router needs the map
from TRAVEL direction -> facing value. Getting this wrong silently kills a net
(n8: signal travelling -z hit a facing=south repeater and stopped).

For each facing f, drive a dust on each of the 4 sides and see which side makes
the repeater output. Then print the correct TRAVEL->FACING table.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1+1):
        for z in range(z0, z1+1):
            B(x, y, z, S)

SIDES = {"west": (-1, 0), "east": (1, 0), "north": (0, -1), "south": (0, 1)}


def probe(facing, drive_side):
    """Put a repeater at origin facing `facing`; drive a dust chain on
    `drive_side`; read all 4 neighbours to see where output appears."""
    sc = nuc.Schematic.create(f"rf_{facing}_{drive_side}")
    B = sc.set_block_from_string
    flr(B, -6, 6, -6, 6)
    ox, oz = 0, 0
    B(ox, 0, oz, f"minecraft:repeater[facing={facing},delay=1]")
    dx, dz = SIDES[drive_side]
    # dust + source going out from that side
    B(ox+dx, 0, oz+dz, W)
    B(ox+2*dx, 0, oz+2*dz, W)
    B(ox+3*dx, 0, oz+3*dz, RB)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(20)
    out = {}
    for name, (qx, qz) in SIDES.items():
        if name == drive_side:
            continue
        # a dust one step out on that side to detect output
        out[name] = w.get_redstone_power(ox+qx, 0, oz+qz)
    return out


if __name__ == "__main__":
    print("repeater facing semantics: which side is INPUT?")
    input_side = {}
    for facing in SIDES:
        for ds in SIDES:
            # place an output-detect dust on the opposite side of the drive
            sc = nuc.Schematic.create(f"t_{facing}_{ds}")
            B = sc.set_block_from_string
            flr(B, -6, 6, -6, 6)
            B(0, 0, 0, f"minecraft:repeater[facing={facing},delay=1]")
            dx, dz = SIDES[ds]
            B(dx, 0, dz, W); B(2*dx, 0, 2*dz, W); B(3*dx, 0, 3*dz, RB)
            # detect on the opposite side
            B(-dx, 0, -dz, W)
            w = nuc.MchprsWorld.create_with_options(sc, True, False)
            w.tick(20)
            p = w.get_redstone_power(-dx, 0, -dz)
            if p > 0:
                input_side[facing] = ds
                print(f"  facing={facing:5s}: INPUT from {ds:5s} -> output {p} on opposite side")
    print()
    print("=> TRAVEL direction -> required facing (repeater must read the side the signal comes from):")
    for facing, ds in input_side.items():
        dx, dz = SIDES[ds]
        travel = (-dx, -dz)   # signal moves FROM that side INTO the repeater
        print(f"  travel {travel} (came from {ds}) -> facing={facing}")
