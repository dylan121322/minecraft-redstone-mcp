"""
test_diagonal.py — DECISIVE test of a claim that changes the whole short model:
does redstone dust couple DIAGONALLY?

Every legality check in route_buildable uses _PLANE_SHELL, which includes the four
diagonals, and _count_shorts flags a diagonal pair as a short. If diagonals do NOT
conduct, that model is far too strict — and the alu1 blocker (n2's feed at
(173,19) vs n17's wire at (172,20)/(173,21), several of which are DIAGONAL) may
not be a real conflict at all.

Cases, all on a flat floor with /setblock-style placement (no block updates):
  D1 pure diagonal: driven dust at (0,0,0), probe dust at (1,0,1). Nothing else.
  D2 diagonal with the two orthogonal cells EMPTY (isolate the diagonal path).
  D3 orthogonal baseline: (0,0,0) -> (1,0,0), must conduct (control).
  D4 two parallel lines one apart diagonally offset — the real router situation:
     line A along z=0, line B along z=2, and a probe at the diagonal between.
  D5 diagonal across a 1-cell gap in the SAME line (dust at (0,0,0) and (1,0,1)
     with (1,0,0) and (0,0,1) both empty) — the "corner" case.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"


def floor(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def run(name, build, probes):
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"{name}_{drive}")
        B = sc.set_block_from_string
        floor(B, -6, 8, -6, 8)
        build(B, drive)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(20)
        out[drive] = {p: w.get_redstone_power(*p) for p in probes}
    return out


def d1(B, drive):
    """pure diagonal: source dust at origin, probe dust diagonally adjacent."""
    B(-2, 0, 0, RB if drive else "minecraft:air")
    B(-1, 0, 0, W)
    B(0, 0, 0, W)          # driven line end
    B(1, 0, 1, W)          # DIAGONAL neighbour — does it light?


def d2(B, drive):
    """diagonal with both orthogonal go-betweens explicitly empty."""
    B(-2, 0, 0, RB if drive else "minecraft:air")
    B(-1, 0, 0, W)
    B(0, 0, 0, W)
    # (1,0,0) and (0,0,1) deliberately left as air
    B(1, 0, 1, W)


def d3(B, drive):
    """orthogonal control: must conduct."""
    B(-2, 0, 0, RB if drive else "minecraft:air")
    B(-1, 0, 0, W)
    B(0, 0, 0, W)
    B(1, 0, 0, W)


def d4(B, drive):
    """two parallel lines 2 apart in z (the cell A/B feed situation).
    Line A (driven) along z=0; line B (undriven, separate net) along z=2.
    Probe line B: if diagonals coupled, B would light."""
    B(-2, 0, 0, RB if drive else "minecraft:air")
    for x in range(-1, 4):
        B(x, 0, 0, W)        # line A, driven
    for x in range(-1, 4):
        B(x, 0, 2, W)        # line B, foreign net
    # z=1 row left empty — this is the single free row between the two pins


def d5(B, drive):
    """corner case: dust at (0,0,0) and (1,0,1), both orthogonal cells air."""
    B(-2, 0, 0, RB if drive else "minecraft:air")
    B(-1, 0, 0, W)
    B(0, 0, 0, W)
    B(1, 0, 1, W)
    B(2, 0, 1, W)            # extend the probe line so it is a real line


if __name__ == "__main__":
    print("=== D3 orthogonal control (MUST conduct) ===")
    r = run("d3", d3, [(1, 0, 0)])
    print(f"  drive0 {r[0]}  drive1 {r[1]}")

    print("\n=== D1 pure diagonal ===")
    r = run("d1", d1, [(1, 0, 1)])
    print(f"  drive0 {r[0]}  drive1 {r[1]}")

    print("\n=== D2 diagonal, orthogonal cells empty ===")
    r = run("d2", d2, [(1, 0, 1)])
    print(f"  drive0 {r[0]}  drive1 {r[1]}")

    print("\n=== D4 two parallel lines 2 apart in z (the real cell-feed case) ===")
    r = run("d4", d4, [(0, 0, 2), (1, 0, 2), (2, 0, 2)])
    print(f"  drive0 {r[0]}")
    print(f"  drive1 {r[1]}")

    print("\n=== D5 corner (diagonal continuation of a line) ===")
    r = run("d5", d5, [(1, 0, 1), (2, 0, 1)])
    print(f"  drive0 {r[0]}  drive1 {r[1]}")

    print("\nIf D1/D2/D5 stay 0 while D3 conducts, dust does NOT couple")
    print("diagonally, and _PLANE_SHELL's 4 diagonal offsets make the router")
    print("reject legal geometry — including alu1's last blocker.")
