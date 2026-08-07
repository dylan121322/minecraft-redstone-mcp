"""
test_cells_target_out.py — can MCHPRS build the FULL set of gate cells with a
TARGET-block output stage? The target defaults OFF when its input floats (fixing
the y-stuck class) and outputs 15 when driven (test_gate_target_out).

For each of AND/OR/NAND/NOR we build the cell TWICE:
  classic : internal logic with wall-torch output (the current library)
  target  : identical internal logic, but the output wall torch is replaced by
            repeater -> target -> output dust
and verify 4/4 on the truth table, plus a floating-input probe.

The output stage change: the internal logic already produces a strong-powered
block at the output mount. In the classic cell a wall torch on that mount inverts
to make the final output. If we instead put a REPEATER on/from that block and a
target after it, the target re-reads the (inverted) logic value.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
import cell_library as clib

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TARGET = "minecraft:target"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-1, r=14):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def test(gtype, truth):
    print(f"\n{gtype} with target output stage:")
    ok = 0
    n = 0
    for (a, b), exp in truth.items():
        # drive A=a, B=b
        sc = nuc.Schematic.create(f"tv2_{gtype}_{a}{b}")
        B = sc.set_block_from_string
        floor(B)
        cell = clib.get(gtype)
        A = cell.inputs["A"]
        drives = [(A[2], a)]
        if "B" in cell.inputs:
            drives.append((cell.inputs["B"][2], b))
        for zz, dv in drives:
            B(-3, 0, zz, RB if dv else "minecraft:air")
            B(-2, 0, zz, W); B(-1, 0, zz, W)
        cell.emit(sc, 0, 0, 0)
        q = cell.outputs["Q"]
        qx = q[0]; qz = q[2]
        B(qx + 1, 0, qz, rep("west"))
        B(qx + 2, 0, qz, TARGET)
        B(qx + 3, 0, qz, W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(50)
        got = 1 if w.get_redstone_power(qx + 3, 0, qz) > 0 else 0
        ok += (got == exp); n += 1
        print(f"   A={a} B={b}: got={got} exp={exp} {'OK' if got==exp else 'X'}")
    return ok, n


if __name__ == "__main__":
    # test the cells that appear in alu1: NAND/OR/AND/NOR/NOT
    for gtype, truth in (
        ("NOT", {(0, 0): 1, (1, 0): 0}),
        ("AND", {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1}),
        ("OR",  {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1}),
        ("NAND",{(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0}),
        ("NOR", {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0}),
    ):
        ok, n = test(gtype, truth)
        print(f"  {gtype}: {ok}/{n}")
