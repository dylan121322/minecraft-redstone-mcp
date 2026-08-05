"""
test_diag_adjacent.py — the case that actually decides the short model.

test_diagonal proved a dust does not CONDUCT to a diagonal neighbour (a signal
cannot travel that way). But "does not conduct" is not the same as "does not
interfere": the router's real question is whether TWO INDEPENDENT NETS whose
wires are diagonally adjacent corrupt each other.

Redstone dust connects to any dust in its 4 orthogonal directions. Two dust cells
that are diagonal to each other have NO direct link — but each of them may link
to the SAME third cell, and a powered dust also powers the block beneath it,
which can feed a torch/repeater. So the honest test drives net A and reads net B
when their wires are:

  A1  diagonally adjacent, nothing else nearby      (the pure question)
  A2  diagonally adjacent, sharing an orthogonal neighbour cell (should couple)
  A3  orthogonally adjacent (control: must couple)
  A4  diagonal, but each line continues so both have their own orthogonal
      neighbours — the layout the router actually produces
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"


def floor(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def run(name, build, probes, ticks=20):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        floor(B, -8, 10, -8, 10)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {p: w.get_redstone_power(*p) for p in probes}
    return out


def a1(B, drive):
    """A ends at (0,0,0); B is a single dust at (1,0,1) — pure diagonal, and B
    has no other neighbours at all."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, W); B(0, 0, 0, W)      # net A
    B(1, 0, 1, W)                                       # net B (isolated dust)


def a2(B, drive):
    """A and B are diagonal AND both touch the same cell (1,0,0)."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, W); B(0, 0, 0, W)      # net A
    B(1, 0, 0, W)                                       # shared cell
    B(1, 0, 1, W)                                       # net B


def a3(B, drive):
    """orthogonal control."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    B(-2, 0, 0, W); B(-1, 0, 0, W); B(0, 0, 0, W)
    B(1, 0, 0, W)


def a4(B, drive):
    """Two parallel lines offset by 1 in z, i.e. every cell of A is diagonal to
    a cell of B. This is the geometry the router calls a short."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    for x in range(-2, 5):
        B(x, 0, 0, W)          # net A along z=0, driven
    for x in range(-2, 5):
        B(x, 0, 1, W)          # net B along z=1 — orthogonally adjacent in z!
    # note: z=0 and z=1 are ORTHOGONAL neighbours, so this must couple.


def a5(B, drive):
    """True diagonal-only parallel: A along z=0, B along z=2, and the lines are
    x-offset so no two cells share an orthogonal neighbour."""
    B(-3, 0, 0, RB if drive else "minecraft:air")
    for x in range(-2, 5):
        B(x, 0, 0, W)          # net A
    for x in range(-2, 5):
        B(x, 0, 2, W)          # net B, two rows away
    # z=1 row empty -> only diagonal-ish separation of 2, must NOT couple


if __name__ == "__main__":
    print("=== A3 orthogonal control (must couple) ===")
    r = run("a3", a3, [(1, 0, 0)])
    print(f"  drive0={r[0]}  drive1={r[1]}")

    print("\n=== A1 pure diagonal, isolated B dust ===")
    r = run("a1", a1, [(1, 0, 1)])
    print(f"  drive0={r[0]}  drive1={r[1]}")

    print("\n=== A2 diagonal but sharing cell (1,0,0) ===")
    r = run("a2", a2, [(1, 0, 1), (1, 0, 0)])
    print(f"  drive0={r[0]}  drive1={r[1]}")

    print("\n=== A4 lines 1 apart in z (ORTHOGONAL, must couple) ===")
    r = run("a4", a4, [(0, 0, 1), (4, 0, 1)])
    print(f"  drive0={r[0]}  drive1={r[1]}")

    print("\n=== A5 lines 2 apart in z (must NOT couple) ===")
    r = run("a5", a5, [(0, 0, 2), (4, 0, 2)])
    print(f"  drive0={r[0]}  drive1={r[1]}")

    print("\nConclusion key:")
    print("  A1=0 -> a lone diagonal dust is NOT driven")
    print("  A2>0 -> diagonals DO couple when they share an orthogonal cell")
    print("  A4>0 -> 1-row separation couples (it is orthogonal, not diagonal)")
    print("  A5=0 -> 2-row separation is safe")
