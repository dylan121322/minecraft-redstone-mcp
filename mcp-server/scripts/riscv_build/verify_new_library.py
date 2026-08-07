"""verify_new_library.py — verify the TARGET-STAGE cell library 4/4 on every
cell, reading the library's own Q position (the stage is now inside the cell)."""
import sys, importlib
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
import cell_library as clib

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"


def floor(B, y=-1, r=14):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, "minecraft:stone")


def build(gtype, ins, ticks=60):
    sc = nuc.Schematic.create(f"nl_{gtype}_{'_'.join(map(str, ins))}")
    B = sc.set_block_from_string
    floor(B)
    cell = clib.get(gtype)
    drives = [(cell.inputs["A"][2], ins[0])]
    if "B" in cell.inputs:
        drives.append((cell.inputs["B"][2], ins[1]))
    for zz, dv in drives:
        B(-3, 0, zz, RB if dv else "minecraft:air")
        B(-2, 0, zz, W); B(-1, 0, zz, W)
    cell.emit(sc, 0, 0, 0)
    q = cell.outputs["Q"]
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return 1 if w.get_redstone_power(q[0], q[1], q[2]) > 0 else 0


if __name__ == "__main__":
    TRUTH = {
        "NOT":  {(0,): 1, (1,): 0},
        "BUF":  {(0,): 0, (1,): 1},
        "AND":  {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1},
        "OR":   {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1},
        "NAND": {(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0},
        "NOR":  {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0},
    }
    allok = True
    for gtype, truth in TRUTH.items():
        ok = n = 0
        for ins, exp in truth.items():
            got = build(gtype, ins)
            ok += (got == exp); n += 1
        allok &= (ok == n)
        print(f"{gtype}: {ok}/{n}")
    print(f"\n=== {'ALL CELLS PASS' if allok else 'SOME FAIL'} ===")
