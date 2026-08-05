"""
cell_library_stag.py — drop-in STAGGERED variants of the 2-input cells.

All four verified 4/4 in MCHPRS (cell_stagger.py). The only change versus
cell_library is that input B moves one cell EAST:

    original   A@(0,0,0)  B@(0,0,2)   -> feed cells (-1,0) and (-1,2): ADJACENT
    staggered  A@(0,0,0)  B@(1,0,2)   -> feed cells (-1,0) and ( 0,2): NOT adjacent

Why it matters: the two inputs of one gate are driven by DIFFERENT nets, and with
the original layout their feed wires are 8-neighbours with a single free row
between them, so the two nets must fight over it. That was proven to be the last
blocker on alu1 (g8_OR at (174,0,19): n2 -> A, n17 -> B, and n17 killed all 28 of
n2's delivery candidates).

Cells get 1 wider in x; depth stays 3. Import this module and call install() to
swap the library, so the change can be A/B measured without touching the
original file.
"""
import cell_library as clib
from cell_library import Cell, W, S, REP_W, _wt


def _emit_or_stag(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)
    B(1, 0, 2, REP_W)
    B(1, 0, 0, W); B(2, 0, 0, W)
    B(2, 0, 2, W)
    B(2, 0, 1, W)
    B(3, 0, 1, W)


def _emit_nor_stag(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)
    B(1, 0, 2, REP_W)
    B(1, 0, 0, W); B(2, 0, 0, W)
    B(2, 0, 2, W)
    B(2, 0, 1, W)
    B(3, 0, 1, W)
    B(4, 0, 1, S); B(5, 0, 1, _wt())
    B(6, 0, 1, W)


def _emit_and_stag(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    B(0, 0, 0, REP_W)
    B(1, 0, 2, REP_W)
    B(1, 0, 0, S); B(2, 0, 0, _wt())
    B(2, 0, 2, S); B(3, 0, 2, _wt())
    B(3, 0, 0, W); B(4, 0, 0, W)
    B(4, 0, 2, W)
    B(4, 0, 1, W)
    B(5, 0, 1, W)
    B(6, 0, 1, S); B(7, 0, 1, _wt())
    B(8, 0, 1, W)


def _emit_nand_stag(schem, ox, oy, oz):
    B = lambda dx, dy, dz, blk: schem.set_block_from_string(ox+dx, oy+dy, oz+dz, blk)
    _emit_and_stag(schem, ox, oy, oz)
    B(9, 0, 1, S); B(10, 0, 1, _wt())
    B(11, 0, 1, W)


# Q positions shift east by 1 relative to the originals (OR 2->3, NOR 5->6,
# AND 7->8, NAND 10->11) because the merge column moved to clear input B.
OR_S = Cell("OR", 4, 1, 3, {"A": (0, 0, 0), "B": (1, 0, 2)},
            {"Q": (3, 0, 1)}, _emit_or_stag)
NOR_S = Cell("NOR", 7, 2, 3, {"A": (0, 0, 0), "B": (1, 0, 2)},
             {"Q": (6, 0, 1)}, _emit_nor_stag)
AND_S = Cell("AND", 9, 2, 3, {"A": (0, 0, 0), "B": (1, 0, 2)},
             {"Q": (8, 0, 1)}, _emit_and_stag)
NAND_S = Cell("NAND", 12, 2, 3, {"A": (0, 0, 0), "B": (1, 0, 2)},
              {"Q": (11, 0, 1)}, _emit_nand_stag)

STAGGERED = {"OR": OR_S, "NOR": NOR_S, "AND": AND_S, "NAND": NAND_S}
_ORIGINALS = {}


def install():
    """Swap the 2-input cells for their staggered variants (idempotent)."""
    if not _ORIGINALS:
        for k in STAGGERED:
            _ORIGINALS[k] = clib.LIBRARY[k]
    clib.LIBRARY.update(STAGGERED)


def uninstall():
    if _ORIGINALS:
        clib.LIBRARY.update(_ORIGINALS)
