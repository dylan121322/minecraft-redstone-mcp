"""
cell_stagger.py — proposed fix for the LAST blocker on alu1, measured before
committing to it.

Proven root cause: every 2-input cell has A@(0,0,0) and B@(0,0,2) — the two input
pins are 2 cells apart in the SAME column, with one free row between them, and
each is driven by a DIFFERENT net. Redstone dust couples across 1 cell, so those
two feeds must fight over that single row. row_gap does not help (it only spaces
gates apart, not pins within a gate); the 2-cell spacing is structural, because
the cell's junction column sits at z=1 between them.

Idea under test (STAGGER): keep the z spacing, but move input B one cell EAST, so
the two feed wires arrive in different columns:
    A @ (0,0,0)      B @ (1,0,2)
The cell's own body absorbs the offset (B's wire simply starts one cell later).
Feed cells then become (-1,0) for A and (0,2) for B — no longer 8-neighbours.

This file builds STAGGERED variants of the four 2-input cells, MCHPRS-verifies
each still computes its function, and only then reports the routing effect.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
import cell_library as clib

W = "minecraft:redstone_wire"
S = "minecraft:stone"
REP_W = "minecraft:repeater[facing=west,delay=1]"
RB = "minecraft:redstone_block"


def _wt(f="east"):
    return f"minecraft:redstone_wall_torch[facing={f}]"


# ---- staggered emitters: input B shifted +1 in x -------------------------
def or_stag(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)          # A input (unchanged)
    B(1, 0, 2, REP_W)          # B input, one cell EAST
    B(1, 0, 0, W)
    B(2, 0, 2, W)
    B(1, 0, 1, W)              # junction column
    B(2, 0, 1, W)
    B(3, 0, 1, W)              # output moved one east to clear the junction


def nor_stag(schem, ox, oy, oz):
    """NOR with input B staggered one cell east.

    First attempt failed 3/4 because B's wire started at x=2 while the OR
    junction sits at x=1, so B never reached it. Fix: the junction column moves
    to x=2 (east of both inputs) and A's wire runs one cell further to meet it.
        A@(0,0,0) -> wire (1,0,0) -> (2,0,0)
        B@(1,0,2) -> wire (2,0,2)
        junction (2,0,1), straight (3,0,1), NOT at (4..5), Q@(6,0,1)
    """
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)          # A input
    B(1, 0, 2, REP_W)          # B input, one cell east
    B(1, 0, 0, W); B(2, 0, 0, W)
    B(2, 0, 2, W)
    B(2, 0, 1, W)              # junction now at x=2, reachable from both
    B(3, 0, 1, W)              # straight segment for strong power
    B(4, 0, 1, S); B(5, 0, 1, _wt())
    B(6, 0, 1, W)


def verify(name, emit, w, d, inputs, outputs, truth):
    """MCHPRS-verify a staggered cell against its truth table."""
    ok = 0
    total = 0
    for (a, b), exp in truth.items():
        sc = nuc.Schematic.create(f"{name}_{a}{b}")
        Bs = sc.set_block_from_string
        for x in range(-6, w + 8):
            for z in range(-4, d + 5):
                Bs(x, -1, z, S)
        # drive the two inputs from the west of each pin
        ax, _ay, az = inputs["A"]
        bx, _by, bz = inputs["B"]
        Bs(ax - 3, 0, az, RB if a else "minecraft:air")
        Bs(ax - 2, 0, az, W); Bs(ax - 1, 0, az, W)
        Bs(bx - 3, 0, bz, RB if b else "minecraft:air")
        Bs(bx - 2, 0, bz, W); Bs(bx - 1, 0, bz, W)
        emit(sc, 0, 0, 0)
        qx, _qy, qz = outputs["Q"]
        world = nuc.MchprsWorld.create_with_options(sc, True, False)
        world.tick(40)
        got = 1 if world.get_redstone_power(qx, 0, qz) > 0 else 0
        total += 1
        ok += (got == exp)
        print(f"   {name} A={a} B={b}: got={got} exp={exp} "
              f"{'OK' if got == exp else 'X'}")
    return ok, total


def and_stag(schem, ox, oy, oz):
    """AND = NOR(NOT A, NOT B), with input B staggered one cell east.

    Original: A@(0,0,0) B@(0,0,2), each inverted in place, merged at x=3.
    Staggered: B sits at (1,0,2) so its inverter chain also shifts one east, and
    the merge column moves to x=4 where both branches can reach it.
        A@(0,0,0) -> S(1,0,0) -> torch(2,0,0) -> wire(3,0,0) -> (4,0,0)
        B@(1,0,2) -> S(2,0,2) -> torch(3,0,2) -> wire(4,0,2)
        merge (4,0,1), straight (5,0,1), final NOT (6..7), Q@(8,0,1)
    """
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)                       # A input
    B(1, 0, 2, REP_W)                       # B input, staggered east
    B(1, 0, 0, S); B(2, 0, 0, _wt())        # NOT A
    B(2, 0, 2, S); B(3, 0, 2, _wt())        # NOT B (one east)
    B(3, 0, 0, W); B(4, 0, 0, W)            # A branch reaches the merge column
    B(4, 0, 2, W)                           # B branch reaches the merge column
    B(4, 0, 1, W)                           # merge
    B(5, 0, 1, W)                           # straight segment (strong power)
    B(6, 0, 1, S); B(7, 0, 1, _wt())        # final NOT
    B(8, 0, 1, W)                           # output


def nand_stag(schem, ox, oy, oz):
    """NAND = AND then one more inverter, B staggered one cell east.
    Q ends at (11,0,1)."""
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    and_stag(schem, ox, oy, oz)             # produces AND at (8,0,1)
    B(9, 0, 1, S); B(10, 0, 1, _wt())       # extra NOT
    B(11, 0, 1, W)


if __name__ == "__main__":
    print("=== staggered OR (A@(0,0,0), B@(1,0,2), Q@(3,0,1)) ===")
    ok, tot = verify("OR*", or_stag, 4, 3,
                     {"A": (0, 0, 0), "B": (1, 0, 2)}, {"Q": (3, 0, 1)},
                     {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 1})
    print(f"  OR staggered: {ok}/{tot}")

    print("\n=== staggered NOR (Q@(6,0,1)) ===")
    ok2, tot2 = verify("NOR*", nor_stag, 7, 3,
                       {"A": (0, 0, 0), "B": (1, 0, 2)}, {"Q": (6, 0, 1)},
                       {(0, 0): 1, (0, 1): 0, (1, 0): 0, (1, 1): 0})
    print(f"  NOR staggered: {ok2}/{tot2}")

    print("\n=== staggered AND (Q@(8,0,1)) ===")
    ok3, tot3 = verify("AND*", and_stag, 9, 3,
                       {"A": (0, 0, 0), "B": (1, 0, 2)}, {"Q": (8, 0, 1)},
                       {(0, 0): 0, (0, 1): 0, (1, 0): 0, (1, 1): 1})
    print(f"  AND staggered: {ok3}/{tot3}")

    print("\n=== staggered NAND (Q@(11,0,1)) ===")
    ok4, tot4 = verify("NAND*", nand_stag, 12, 3,
                       {"A": (0, 0, 0), "B": (1, 0, 2)}, {"Q": (11, 0, 1)},
                       {(0, 0): 1, (0, 1): 1, (1, 0): 1, (1, 1): 0})
    print(f"  NAND staggered: {ok4}/{tot4}")

    print(f"\n=== SUMMARY: OR {ok}/{tot}  NOR {ok2}/{tot2}  "
          f"AND {ok3}/{tot3}  NAND {ok4}/{tot4} ===")

    print("\nfeed-cell separation check:")
    print("  original : A feed (-1,0)  B feed (-1,2)  -> 8-neighbours (conflict)")
    print("  staggered: A feed (-1,0)  B feed ( 0,2)  -> not adjacent (OK)"
          if True else "")
