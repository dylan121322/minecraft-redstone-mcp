"""
test_gate_target_out.py — replace a gate's wall-torch output with a TARGET-block
output and verify the gate still computes its function, plus the floating-input
case now yields 0 (not 1).

The y-stuck bug: gate output torch defaults ON when the input floats. A target
block, driven by the gate's internal logic through a repeater, defaults OFF and
only outputs when actually driven (test_target_mchprs T3/T4).

Build a NOT gate both ways:
  NOT-A (classic) : input -> stone -> wall_torch -> output dust
  NOT-B (target)  : input -> stone -> wall_torch -> (inverts) -> repeater ->
                    target -> output dust
And the floating case: gate input left unconnected -> classic gives 1, target
gives 0.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TARGET = "minecraft:target"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-1, r=10):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def not_classic(B, drive, ox=0, oz=0):
    """classic NOT: input dust -> stone mount -> wall torch -> output dust."""
    B(ox - 2, 0, oz, RB if drive else "minecraft:air")
    B(ox - 1, 0, oz, W)
    B(ox + 0, 0, oz, W)             # input dust
    B(ox + 1, 0, oz, S)             # mount
    B(ox + 2, 0, oz, wt("east"))    # torch reads mount
    B(ox + 3, 0, oz, W)             # output


def not_target(B, drive, ox=0, oz=0):
    """target NOT: input -> mount -> torch -> repeater -> target -> output."""
    B(ox - 2, 0, oz, RB if drive else "minecraft:air")
    B(ox - 1, 0, oz, W)
    B(ox + 0, 0, oz, W)             # input dust
    B(ox + 1, 0, oz, S)             # mount
    B(ox + 2, 0, oz, wt("east"))    # torch (inverts)
    B(ox + 3, 0, oz, S)             # block the torch powers? torch powers block above
    B(ox + 3, 1, oz, W)             # read the torch's output dust
    B(ox + 4, 1, oz, rep("west"))   # re-drive
    B(ox + 5, 1, oz, TARGET)        # target as the new output node
    B(ox + 6, 1, oz, W)             # final output dust


def not_target_simple(B, drive, ox=0, oz=0):
    """target NOT, simpler: input -> repeater -> target -> output.
    The target defaults OFF; driven by the repeater it outputs 15."""
    B(ox - 2, 0, oz, RB if drive else "minecraft:air")
    B(ox - 1, 0, oz, W)
    B(ox + 0, 0, oz, rep("west"))
    B(ox + 1, 0, oz, TARGET)
    B(ox + 2, 0, oz, W)


def run(build, probes, ticks=40):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"g_{drive}")
        B = sc.set_block_from_string
        floor(B)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {p: w.get_redstone_power(*p) for p in probes}
    return out


if __name__ == "__main__":
    print("classic NOT (torch output):")
    r = run(not_classic, [(3, 0, 0)])
    print(f"   {r}   expected {{0: 0->1, 1: 1->0}}? drive0 out={r[0][(3,0,0)]} drive1={r[1][(3,0,0)]}")
    print("\ntarget NOT (repeater -> target -> dust):")
    r = run(not_target_simple, [(2, 0, 0)])
    print(f"   {r}")
    print("\nfloating input case (input unconnected):")
    # build with no driver at all
    sc = nuc.Schematic.create("float_c")
    B = sc.set_block_from_string
    floor(B)
    not_classic(B, 0, 0, 0)
    not_target_simple(B, 0, 6, 0)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(40)
    print(f"   classic output={w.get_redstone_power(3,0,0)}  "
          f"target output={w.get_redstone_power(8,0,0)}")
    print("   (classic should read 1 = stuck-high; target should read 0 = off)")
