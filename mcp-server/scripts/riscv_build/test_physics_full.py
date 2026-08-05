"""
test_physics_full.py — exhaustive map of how two INDEPENDENT nets can corrupt each
other, so the router's legality rule can be tightened/loosened from measurement
instead of guesswork.

Why: relaxing the shell from 8-neighbour to "orthogonal + diagonal-with-shared-
cell" improved alu1 but introduced REAL shorts on Mux2to1 (6) and ImmGen (3),
proving the relaxed predicate misses coupling paths. This enumerates every
plausible path on a flat /setblock build and reports which geometries couple.

Coupling channels tested:
  P1  orthogonal dust-dust (baseline)
  P2  diagonal dust-dust, victim isolated
  P3  diagonal dust-dust sharing an occupied orthogonal cell
  P4  dust over/under: driven dust at y0, victim dust at y1 same column
  P5  dust diagonal in Y: driven (0,0,0), victim (1,1,0) — the ramp case
  P6  SEE-BELOW: victim dust one level lower and one cell across
  P7  strong power through a BLOCK: driven dust -> block -> victim dust on top
  P8  block side: driven dust powers block; victim dust beside the same block
  P9  repeater side/back leakage (already known isolated, re-confirm)
  P10 torch: victim dust beside a lit torch's block
  P11 two dust separated by a solid block (should be safe)
  P12 dust and victim 2 apart same layer (should be safe)
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
T = "minecraft:redstone_torch"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def flat(B, y=-1, r=10):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def probe(name, build, victims, ticks=25):
    """Returns {drive: {victim: power}}. A victim that changes with drive is
    COUPLED."""
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        flat(B)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        out[drive] = {v: w.get_redstone_power(*v) for v in victims}
    return out


def src(B, drive, x=-3, y=0, z=0, n=3):
    """A driven dust line ending at (x+n-1, y, z)."""
    B(x - 1, y, z, RB if drive else "minecraft:air")
    for i in range(n):
        B(x + i, y, z, W)


CASES = {}


def case(name, victims, ticks=25):
    def deco(f):
        CASES[name] = (f, victims, ticks)
        return f
    return deco


@case("P1 orthogonal dust-dust", [(1, 0, 0)])
def p1(B, d):
    src(B, d, -3, 0, 0, 4)          # ends at (0,0,0)
    B(1, 0, 0, W)


@case("P2 diagonal, victim isolated", [(1, 0, 1)])
def p2(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 1, W)


@case("P3 diagonal + shared orthogonal cell", [(1, 0, 1)])
def p3(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, W)                   # shared cell
    B(1, 0, 1, W)


@case("P4 victim directly ABOVE (y+1)", [(0, 1, 0)])
def p4(B, d):
    src(B, d, -3, 0, 0, 4)
    B(0, 1, 0, S)                   # needs support? put dust on a block beside
    B(1, 1, 0, W)
    CASES  # noqa
@case("P4b victim dust on a block above the line", [(1, 1, 0)])
def p4b(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, S)                   # block east of the line end
    B(1, 1, 0, W)                   # dust on top of that block


@case("P5 victim diagonal in Y (ramp)", [(1, 1, 0)])
def p5(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, S); B(1, 1, 0, W)


@case("P6 see-below: victim one lower, one across", [(1, -1, 0)])
def p6(B, d):
    # driven line at y=0 on a raised floor; victim one level down beside it
    for x in range(-4, 3):
        B(x, -1, 0, S)
    src(B, d, -3, 0, 0, 4)
    B(1, -1, 0, W)                  # victim on the lower floor


@case("P7 strong power via block: dust->block->dust on top", [(1, 1, 0)])
def p7(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, S)
    B(1, 1, 0, W)


@case("P8 victim beside a block the line powers", [(2, 0, 1)])
def p8(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, S)                   # block powered by the dust
    B(2, 0, 1, W)                   # victim diagonal to the block


@case("P9 repeater side leakage", [(1, 0, 1), (1, 0, -1)])
def p9(B, d):
    src(B, d, -4, 0, 0, 3)
    B(0, 0, 0, rep("west"))
    B(1, 0, 0, W)
    B(1, 0, 1, W); B(1, 0, -1, W)


@case("P10 victim beside a lit torch's mount", [(2, 0, 1), (2, 1, 0)])
def p10(B, d):
    src(B, d, -4, 0, 0, 3)
    B(0, 0, 0, S)                   # mount, powered when driven
    B(1, 0, 0, wt("east"))          # torch: OFF when mount powered
    B(2, 0, 0, W)
    B(2, 0, 1, W)
    B(2, 1, 0, W)


@case("P11 two dust separated by a solid block", [(2, 0, 0)])
def p11(B, d):
    src(B, d, -3, 0, 0, 4)
    B(1, 0, 0, S)                   # solid separator
    B(2, 0, 0, W)


@case("P12 two apart, same layer", [(2, 0, 0)])
def p12(B, d):
    src(B, d, -3, 0, 0, 4)
    B(2, 0, 0, W)                   # (1,0,0) left empty


if __name__ == "__main__":
    print(f"{'case':46s} {'drive0':>28s} {'drive1':>28s}  verdict")
    print("-" * 112)
    for name, (fn, victims, ticks) in CASES.items():
        try:
            r = probe(name, fn, victims, ticks)
        except Exception as e:
            print(f"{name:46s} ERROR {type(e).__name__}: {e}")
            continue
        coupled = any(r[0][v] != r[1][v] for v in victims)
        v0 = ", ".join(f"{v[0]},{v[1]},{v[2]}={r[0][v]}" for v in victims)
        v1 = ", ".join(f"{v[0]},{v[1]},{v[2]}={r[1][v]}" for v in victims)
        print(f"{name:46s} {v0:>28s} {v1:>28s}  "
              f"{'COUPLED' if coupled else 'isolated'}")
