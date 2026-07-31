"""
test_sealed.py — SEALED per-stage tests for the sink delivery path.

Why sealed: every previous round read the tower's bottom cell to judge its
polarity, but that cell belongs to BOTH the tower's last rung and the run heading
for the pin, so its reading changed with the downstream layout. That produced a
string of contradictory conclusions (non-inverting / always inverting /
non-inverting again) from the same geometry.

Rules here:
  * one stage per test, nothing else in the world;
  * an explicit INPUT cell that only the driver touches;
  * an explicit OUTPUT cell that nothing else touches;
  * a wide empty margin so no neighbouring structure couples in;
  * strict judgement in BOTH directions (drive1 and drive0).

Stages, in the order the signal travels:
  S1  trunk dust  -> parity bridge      -> dust one level lower
  S2  dust        -> 2x2 DOWN tower     -> dust at y0        (polarity measured)
  S3  dust at y0  -> straight run       -> dust
  S4  dust at y0  -> inverter           -> dust
  S5  dust at y0  -> gate input pin     -> pin output
Then S2+S4 (+S3) composed, once each stage's polarity is a known fact.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
from via_gadget import down_tower_cells_dir, inverter_cells

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def repw(): return "minecraft:repeater[facing=west,delay=1]"

MARGIN = 8


def sealed(emit, in_cell, out_cell, extent, drive, ticks=60):
    """Build ONE stage in an otherwise empty world.

    emit(B) lays the stage. in_cell is fed by a redstone_block placed one cell to
    its west with a dust between, so the drive path never overlaps the stage.
    Returns the power at out_cell.
    """
    (x0, x1, y0, y1, z0, z1) = extent
    sc = nuc.Schematic.create("sealed")
    B = sc.set_block_from_string
    for x in range(x0 - MARGIN, x1 + MARGIN + 1):
        for z in range(z0 - MARGIN, z1 + MARGIN + 1):
            B(x, y0 - 1, z, S)
    # driver: block -> dust -> repeater -> the stage's input cell
    ix, iy, iz = in_cell
    for k, xx in enumerate((ix - 4, ix - 3, ix - 2)):
        if iy - 1 >= y0 - 1:
            B(xx, iy - 1, iz, S)
    B(ix - 4, iy, iz, RB if drive else "minecraft:air")
    B(ix - 3, iy, iz, W)
    B(ix - 2, iy, iz, repw())
    B(ix - 1, iy, iz, S)          # the repeater drives this block
    B(ix, iy, iz, W)              # the stage's input dust sits on it
    if iy - 1 >= y0 - 1:
        B(ix, iy - 1, iz, S)
    emit(B)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return w.get_redstone_power(*out_cell)


def report(name, fn, expect_invert=None):
    p1 = fn(1)
    p0 = fn(0)
    if p1 > 0 and p0 == 0:
        verdict = "PASS non-inverting"
    elif p1 == 0 and p0 > 0:
        verdict = "PASS inverting"
    else:
        verdict = "BROKEN (no response)"
    print(f"  {name:34s} drive1={p1:2d} drive0={p0:2d}   {verdict}")
    return verdict


# ---------- S1: parity bridge (one see-below step down) ----------
def s1(drive, ty=9, z=0):
    inp = (10, ty, z)
    out = (11, ty - 1, z)

    def emit(B):
        B(11, ty - 2, z, S)
        B(11, ty - 1, z, W)
    return sealed(emit, inp, out, (0, 20, 0, ty + 2, z, z), drive)


# ---------- S2: the DOWN tower alone ----------
def s2(drive, arm=(1, 0), side=(0, 1), ty=8, z=0):
    """Input dust at the shaft top; output is the tower's bottom dust in the A
    column. Nothing else touches that cell — that is the whole point."""
    shaft = 10
    inp = (shaft, ty, z)
    out = (shaft, 0, z)

    def emit(B):
        cells, _ = down_tower_cells_dir(shaft, z, ty, 0, side=side, arm=arm)
        for (x, y, zz, b) in cells:
            B(x, y, zz, b)
    return sealed(emit, inp, out, (0, shaft + 6, 0, ty + 2, z - 2, z + 2), drive)


# ---------- S3: a plain straight run at y0 ----------
def s3(drive, n=4, z=0):
    inp = (10, 0, z)
    out = (10 + n, 0, z)

    def emit(B):
        for i in range(1, n + 1):
            B(10 + i, 0, z, W)
    return sealed(emit, inp, out, (0, 20 + n, 0, 2, z, z), drive)


# ---------- S4: the inverter alone ----------
def s4(drive, z=0, lead=3):
    """The inverter, fed through a few cells of plain dust so its input block is
    driven by DUST only. Feeding it straight off the sealed driver put two solid
    blocks back to back (the driver's block and the inverter's), which double-fed
    the input and pinned the output high."""
    inp = (10, 0, z)
    start = 10 + lead

    def emit(B):
        for i in range(1, lead + 1):
            B(10 + i, 0, z, W)
        cells, _out = inverter_cells(start, 0, z, direction=(1, 0))
        for (x, y, zz, b) in cells:
            B(x, y, zz, b)
    _cells, out = inverter_cells(start, 0, z, direction=(1, 0))
    return sealed(emit, inp, out, (0, 26, 0, 2, z, z), drive)


# ---------- S5: the gate input pin ----------
def s5(drive, z=0):
    inp = (10, 0, z)
    out = (12, 0, z)

    def emit(B):
        B(11, 0, z, repw())      # the pin reads its west neighbour
        B(12, 0, z, W)           # what the gate would drive
    return sealed(emit, inp, out, (0, 20, 0, 2, z, z), drive)


# ---------- composed: parity bridge + tower + run + pin ----------
def composed(drive, arm=(1, 0), side=(0, 1), ty=9, z=0, run=4):
    """The whole sink delivery, still sealed from anything else. Each stage's own
    polarity is now a measured fact (all non-inverting), so a failure here is a
    JOINT failure — which is what the module was actually suffering from."""
    shaft = 12
    inp = (shaft - 1, ty, z)          # trunk dust arriving from the west

    def emit(B):
        # parity bridge: step down one level onto the shaft column
        B(shaft, ty - 2, z, S)
        B(shaft, ty - 1, z, W)
        # tower from the (now even) height down to y0
        cells, _ = down_tower_cells_dir(shaft, z, ty - 1, 0, side=side, arm=arm)
        for (x, y, zz, b) in cells:
            B(x, y, zz, b)
        # run east from the tower's bottom dust, then the pin
        for i in range(1, run + 1):
            B(shaft + i, 0, z, W)
        B(shaft + run + 1, 0, z, repw())
        B(shaft + run + 2, 0, z, W)

    out = (shaft + run + 2, 0, z)
    return sealed(emit, inp, out,
                  (0, shaft + run + 8, 0, ty + 2, z - 3, z + 3), drive, ticks=90)


def composed_nobridge(drive, arm=(1, 0), side=(0, 1), ty=8, z=0, run=4):
    """Same delivery but with NO parity bridge: the trunk already sits at an even
    height, so the tower spans an even number of levels and keeps its measured
    non-inverting behaviour."""
    shaft = 12
    inp = (shaft - 1, ty, z)

    def emit(B):
        B(shaft, ty - 1, z, S)
        B(shaft, ty, z, W)                # shaft top dust, same height as trunk
        cells, _ = down_tower_cells_dir(shaft, z, ty, 0, side=side, arm=arm)
        for (x, y, zz, b) in cells:
            B(x, y, zz, b)
        for i in range(1, run + 1):
            B(shaft + i, 0, z, W)
        B(shaft + run + 1, 0, z, repw())
        B(shaft + run + 2, 0, z, W)

    out = (shaft + run + 2, 0, z)
    return sealed(emit, inp, out,
                  (0, shaft + run + 8, 0, ty + 2, z - 3, z + 3), drive, ticks=90)


def tower_plus_inverter(drive, arm=(0, 1), side=(1, 0), ty=9, z=0, lead=3, run=3):
    """The delivery the module should emit: trunk -> parity bridge -> DOWN tower
    (inverts in real use) -> a few cells of dust -> INVERTER (inverts) -> run ->
    gate pin. Two inversions cancel, so the whole path is non-inverting."""
    shaft = 12
    inp = (shaft - 1, ty, z)
    inv_at = shaft + lead

    def emit(B):
        B(shaft, ty - 2, z, S)
        B(shaft, ty - 1, z, W)
        cells, _ = down_tower_cells_dir(shaft, z, ty - 1, 0, side=side, arm=arm)
        for (x, y, zz, b) in cells:
            B(x, y, zz, b)
        # dust lead so the inverter's input block is driven by dust only
        for i in range(1, lead + 1):
            B(shaft + i, 0, z, W)
        icells, iout = inverter_cells(inv_at, 0, z, direction=(1, 0))
        for (x, y, zz, b) in icells:
            B(x, y, zz, b)
        for i in range(1, run + 1):
            B(iout[0] + i, 0, z, W)
        B(iout[0] + run + 1, 0, z, repw())
        B(iout[0] + run + 2, 0, z, W)

    _ic, iout = inverter_cells(inv_at, 0, z, direction=(1, 0))
    out = (iout[0] + run + 2, 0, z)
    return sealed(emit, inp, out,
                  (0, out[0] + 6, 0, ty + 2, z - 3, z + 3), drive, ticks=100)


if __name__ == "__main__":
    print("=== sealed stage tests (one stage per world, no shared cells) ===")
    report("S1 parity bridge", s1)
    for arm, side in (((1, 0), (0, 1)), ((1, 0), (0, -1)),
                      ((0, 1), (1, 0)), ((0, -1), (1, 0))):
        report(f"S2 DOWN tower arm={arm} side={side}",
               lambda d, a=arm, s=side: s2(d, arm=a, side=s))
    report("S3 straight run (4 cells)", s3)
    report("S4 inverter", s4)
    report("S5 gate input pin", s5)

    print("\n=== composed delivery (bridge + tower + run + pin), sealed ===")
    for arm, side in (((1, 0), (0, 1)), ((1, 0), (0, -1)),
                      ((0, 1), (1, 0)), ((0, -1), (1, 0))):
        report(f"C arm={arm} side={side}",
               lambda d, a=arm, s=side: composed(d, arm=a, side=s))

    # The stages are each non-inverting, yet bridge+tower together invert: the
    # parity bridge costs the tower one level, flipping its torch count from even
    # to odd. Dropping the bridge (an even trunk height needs none) should restore
    # a non-inverting delivery.
    print("\n=== composed WITHOUT the parity bridge (even trunk height) ===")
    for ty in (8, 12):
        for arm, side in (((1, 0), (0, 1)), ((0, 1), (1, 0))):
            report(f"C ty={ty} arm={arm} side={side}",
                   lambda d, a=arm, s=side, t=ty: composed_nobridge(d, arm=a,
                                                                    side=s, ty=t))

    # Established facts: in real use (signal entering the shaft top sideways from
    # the trunk) the tower INVERTS, and the inverter inverts. Chaining the two must
    # therefore be non-inverting — the delivery the module needs.
    print("\n=== tower + inverter (the fix), sealed ===")
    for arm, side in (((0, 1), (1, 0)), ((0, -1), (1, 0))):
        report(f"FIX arm={arm} side={side}",
               lambda d, a=arm, s=side: tower_plus_inverter(d, arm=a, side=s))
