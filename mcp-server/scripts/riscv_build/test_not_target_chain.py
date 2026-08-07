"""
test_not_target_chain.py — the exact NOT geometry with a target output:
    input(W) -> mount(S) -> wall_torch -> repeater -> target -> output(W)
The torch inverts; the repeater re-drives; the target reads it and provides the
default-OFF output. Also check the floating-input case reads 0.
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


def build(B, drive):
    """NOT cell with the output torch replaced by repeater->target->dust.
    Classic NOT: input(W) -> mount(S) -> wall_torch(east) -> output W at (3,0,0).
    New: the torch stays, its output dust is read by a repeater, then target,
    then output dust."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W)
    B(-1, 0, 0, W)                  # drives the input pin (repeater)
    B(0, 0, 0, rep("west"))         # input pin (as in the real cell)
    B(1, 0, 0, S)                   # mount
    B(2, 0, 0, wt("east"))          # torch: OFF when mount powered
    B(3, 0, 0, W)                   # torch's output dust (the classic Q)
    B(4, 0, 0, rep("west"))         # repeater reads Q (facing west => in from west)
    B(5, 0, 0, TARGET)              # target output stage
    B(6, 0, 0, W)                   # final output dust


def run(probe, ticks=50):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"nt_{drive}")
        B = sc.set_block_from_string
        floor(B)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {p: w.get_redstone_power(*p) for p in probe}
    return out


if __name__ == "__main__":
    r = run([(3, 0, 0), (6, 0, 0)])
    print("NOT target-chain (drive0 should give 1, drive1 give 0):")
    print(f"  drive0: torch_out={r[0][(3,0,0)]} final={r[0][(6,0,0)]}")
    print(f"  drive1: torch_out={r[1][(3,0,0)]} final={r[1][(6,0,0)]}")
    # floating case
    sc = nuc.Schematic.create("nt_float")
    B = sc.set_block_from_string
    floor(B)
    build(B, 0)                      # drive=0 but with the driver cell AIR
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(50)
    print(f"  floating input: final={w.get_redstone_power(6,0,0)}")
