"""
test_cell_target_stage.py — add a TARGET output stage to the real library cells
and verify 4/4 truth tables. The target stage is:
    Q(dust) -> repeater -> target -> new Q(dust)
The target isolates the output: downstream nets cannot drive the gate backward,
and the output node is readable-but-not-conductive.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
import cell_library as clib

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TARGET = "minecraft:target"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-1, r=14):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def build(gtype, inputs, extra_stage=True, ticks=50):
    sc = nuc.Schematic.create(f"cs_{gtype}_{'_'.join(map(str, inputs))}")
    B = sc.set_block_from_string
    floor(B)
    cell = clib.get(gtype)
    A = cell.inputs["A"]
    drives = [(A[2], inputs[0])]
    if "B" in cell.inputs:
        drives.append((cell.inputs["B"][2], inputs[1]))
    for zz, dv in drives:
        B(-3, 0, zz, RB if dv else "minecraft:air")
        B(-2, 0, zz, W); B(-1, 0, zz, W)
    cell.emit(sc, 0, 0, 0)
    q = cell.outputs["Q"]
    qx, qz = q[0], q[2]
    if extra_stage:
        B(qx + 1, 0, qz, rep("west"))
        B(qx + 2, 0, qz, TARGET)
        B(qx + 3, 0, qz, W)
        read = (qx + 3, 0, qz)
    else:
        read = (qx, 0, qz)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return 1 if w.get_redstone_power(*read) > 0 else 0


if __name__ == "__main__":
    TRUTH = {
        "NOT":  {(0,): 1, (1,): 0},
        "AND":  {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1},
        "OR":   {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1},
        "NAND": {(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0},
        "NOR":  {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0},
    }
    for gtype, truth in TRUTH.items():
        ok = n = 0
        for ins, exp in truth.items():
            got = build(gtype, ins, extra_stage=True)
            ok += (got == exp); n += 1
        print(f"{gtype} + target stage: {ok}/{n}")
    print("\n(also run one cell WITHOUT the stage to confirm parity)")
    for gtype, truth in (("NAND", TRUTH["NAND"]), ("OR", TRUTH["OR"])):
        ok = n = 0
        for ins, exp in truth.items():
            got = build(gtype, ins, extra_stage=False)
            ok += (got == exp); n += 1
        print(f"{gtype} classic: {ok}/{n}")
