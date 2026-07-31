"""
test_inverter.py — a standalone INVERTER primitive, to compensate the DOWN tower's
constant inversion.

Measured facts this is built on:
  * the 2x2 DOWN tower inverts regardless of cycle count (8/10/12 torches all
    inverted), so a delivery through it needs exactly one more inversion;
  * a wall torch attaches to the block on the side OPPOSITE its facing, and when
    lit it powers every adjacent cell except its support, plus the cell above
    (test_walltorch_attach).

Candidate geometries, all on one y level so they can be dropped into a y0 feed run:

  I1  dust -> block -> wall torch on the far face -> output dust
      (the classic torch inverter; the torch reads the block the input powers)
  I2  same but reading the block from the side, output taken from the torch's own
      cell neighbours
  I3  dust -> block, torch on TOP of the block (standing), output dust one level
      up — needs a step back down, listed for completeness

Judged strictly: drive1 must give output 0 and drive0 must give output > 0, and the
output must actually drive a west-facing repeater (a gate input pin).
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"


def slab(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def I1(drive, z=4):
    """input dust at x=0..2 -> block at x=3 -> torch at x=4 facing east
    (support = the block to its west) -> output dust x=5.., pin at x=8."""
    sc = nuc.Schematic.create(f"i1_{drive}")
    B = sc.set_block_from_string
    slab(B, -4, 14, 0, z + 4)
    B(0, 0, z, RB if drive else "minecraft:air")
    B(1, 0, z, W)
    B(2, 0, z, W)
    B(3, 0, z, S)              # block driven by the input dust
    B(4, 0, z, wt("east"))     # support is (3,0,z) to its west
    B(5, 0, z, W)
    B(6, 0, z, W)
    B(7, 0, z, repw())         # the gate input pin
    B(8, 0, z, W)              # pin output
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(30)
    return (w.get_redstone_power(2, 0, z),      # input side
            w.get_redstone_power(5, 0, z),      # inverter output
            w.get_redstone_power(8, 0, z))      # after the pin


def I2(drive, z=4):
    """Torch mounted on the SIDE (z-1) of the driven block, output continues east
    on the same row — keeps the run straight, no z detour for the signal."""
    sc = nuc.Schematic.create(f"i2_{drive}")
    B = sc.set_block_from_string
    slab(B, -4, 14, 0, z + 4)
    B(0, 0, z, RB if drive else "minecraft:air")
    B(1, 0, z, W)
    B(2, 0, z, W)
    B(3, 0, z, S)
    B(3, 0, z - 1, wt("north"))   # support is (3,0,z) to its south
    B(4, 0, z - 1, W)
    B(4, 0, z, W)
    B(5, 0, z, W)
    B(6, 0, z, repw())
    B(7, 0, z, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(30)
    return (w.get_redstone_power(2, 0, z),
            w.get_redstone_power(4, 0, z),
            w.get_redstone_power(7, 0, z))


def I3(drive, z=4):
    """Standing torch on top of the driven block; output dust sits one level up,
    then a see-below step returns to y0."""
    sc = nuc.Schematic.create(f"i3_{drive}")
    B = sc.set_block_from_string
    slab(B, -4, 14, 0, z + 4)
    B(0, 0, z, RB if drive else "minecraft:air")
    B(1, 0, z, W)
    B(2, 0, z, W)
    B(3, 0, z, S)
    B(3, 1, z, "minecraft:redstone_torch")   # standing torch, powers the cell above
    B(4, 1, z, S)
    B(4, 2, z, W)
    B(5, 1, z, S)
    B(5, 2, z, W)
    B(6, 1, z, W)                            # step down
    B(7, 0, z, W)
    B(8, 0, z, repw())
    B(9, 0, z, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(30)
    return (w.get_redstone_power(2, 0, z),
            w.get_redstone_power(4, 2, z),
            w.get_redstone_power(9, 0, z))


if __name__ == "__main__":
    print("=== inverter candidates (strict: drive1 -> out 0, drive0 -> out > 0) ===")
    for name, fn in (("I1 torch east of block", I1),
                     ("I2 torch on block side", I2),
                     ("I3 standing torch + step down", I3)):
        i1, o1, p1 = fn(1)
        i0, o0, p0 = fn(0)
        ok = (o1 == 0 and o0 > 0)
        pin_ok = (p1 == 0 and p0 > 0)
        print(f"  {name}")
        print(f"     drive1: in={i1:2d} out={o1:2d} after_pin={p1:2d}")
        print(f"     drive0: in={i0:2d} out={o0:2d} after_pin={p0:2d}")
        print(f"     inverts={'YES' if ok else 'no'}  drives pin={'YES' if pin_ok else 'no'}")
