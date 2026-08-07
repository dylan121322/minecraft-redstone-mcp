"""
test_target_mchprs.py — is the target block usable as a GATE OUTPUT that does
not default to 1 when its input floats? And how does it behave when powered by
redstone?

The current killer bug: a gate's output wall torch defaults ON when the gate's
input floats (torch ON = output 1), which pins y to 1 across every configuration.
If a target block does NOT emit when its input is unpresent, it fixes the
floating-input class outright.

Tests:
  T1 target driven by dust: does it conduct/power adjacent dust?
  T2 target as output: target ON a block powered by dust; read dust beside it
     when the driver is 0 (floating) and 1
  T3 target powered by a repeater
  T4 does a target emit at all with NO power? (default-off check)
  T5 comparator reading a target: does it see the target's state?
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TARGET = "minecraft:target"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"
def cmp(f): return f"minecraft:comparator[facing={f},mode=compare]"


def floor(B, y=-1, r=10):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def run(name, build, probes, ticks=30):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {p: w.get_redstone_power(*p) for p in probes}
    return out


def t1(B, drive):
    """dust -> target -> dust: does the target CONDUCT redstone?"""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, W)
    B(0, 0, 0, TARGET)
    B(1, 0, 0, W); B(2, 0, 0, W)


def t2(B, drive):
    """target as OUTPUT: block powered by dust, target on top, read beside."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, W)
    B(0, 0, 0, S)
    B(0, 1, 0, TARGET)          # target on the powered block
    B(1, 1, 0, W)               # read dust beside the target


def t3(B, drive):
    """repeater -> target -> read."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, rep("west"))
    B(0, 0, 0, TARGET)
    B(1, 0, 0, W)


def t4(B, drive):
    """target with NO power: does it emit anything at all?"""
    B(0, 0, 0, TARGET)
    B(1, 0, 0, W)
    B(-1, 0, 0, W)
    # also a target sitting on the bare floor, read from all sides
    B(0, 0, 0, TARGET)


def t5(B, drive):
    """comparator reading the target: does it see the state?"""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, rep("west"))
    B(0, 0, 0, TARGET)
    B(1, 0, 0, cmp("east"))     # comparator reads the target behind it
    B(2, 0, 0, W)


if __name__ == "__main__":
    print("T1 dust->target->dust (does target conduct?):")
    print(f"   {run('t1', t1, [(2, 0, 0)])}")
    print("T2 target as output on a powered block:")
    print(f"   {run('t2', t2, [(1, 1, 0)])}")
    print("T3 repeater->target->dust:")
    print(f"   {run('t3', t3, [(1, 0, 0)])}")
    print("T4 target with NO power (default-off?):")
    print(f"   {run('t4', t4, [(1, 0, 0), (-1, 0, 0)])}")
    print("T5 comparator reading target:")
    print(f"   {run('t5', t5, [(2, 0, 0)])}")
    print("\nKey: does drive=0 give 0 (default-off) while drive=1 gives >0?")
