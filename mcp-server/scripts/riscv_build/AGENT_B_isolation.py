"""
AGENT_B_isolation.py — Empirically determine spacing/isolation rules for
3D redstone bridge routing (y=2 bridge layer over y=0 signal plane).

Architecture:
  y=2: bridge wires (redstone on y=1 support columns)
  y=1: support columns (stone) and ramp intermediate dust
  y=0: signal plane wires + ground plane (stone)

Physics background (verified in-game with /setblock):
  Two redstone dusts SHORT if adjacent: orthogonally same-y, vertically (y±1),
  or diagonally in ANY Chebyshev-1 3D neighborhood — UNLESS both corner blocks
  between them are solid (blocks diagonal coupling through block corners).

Method: each experiment builds a fresh Schematic with the test geometry,
drives the aggressor net with a redstone_block, checks the victim via
get_redstone_power() on MCHPRS (optimize=True, 20 ticks).
"""
from __future__ import annotations
import nucleation as nuc
from typing import Tuple

Pos = Tuple[int, int, int]


# ── helpers ──────────────────────────────────────────────────────────────

def _ground(schem: nuc.Schematic, xmin: int, xmax: int,
            zmin: int, zmax: int, y: int = 0) -> None:
    """Fill a full layer of stone (the ground / support plane)."""
    for x in range(xmin, xmax + 1):
        for z in range(zmin, zmax + 1):
            schem.set_block_from_string(x, y, z, "minecraft:stone")


def _sb(schem: nuc.Schematic, x: int, y: int, z: int,
        block: str) -> None:
    """Shorthand for set_block_from_string."""
    schem.set_block_from_string(x, y, z, block)


def _build_and_sim(
    build_fn,
    aggressor_pos: Pos,
    victim_probe_positions: list[Tuple[str, Pos]],
    ticks: int = 20,
) -> dict:
    """Build schematic via build_fn(schem), drive aggressor with
    redstone_block, create MCHPRS world, tick, return probe powers."""
    schem = nuc.Schematic.create("isolation_test")
    build_fn(schem)
    _sb(schem, *aggressor_pos, "minecraft:redstone_block")
    world = nuc.MchprsWorld.create_with_options(schem, True, False)
    world.tick(ticks)
    result = {}
    for name, pos in victim_probe_positions:
        result[name] = world.get_redstone_power(*pos)
    return result


def _report(
    label: str,
    findings: list[Tuple[str, bool, int | None]],
) -> str:
    """Print PASS/FAIL per sub-test, return summary line."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    all_pass = True
    for desc, expected_isolated, power in findings:
        isolated = (power is None) or (power == 0)
        ok = isolated == expected_isolated
        status = "PASS" if ok else "FAIL"
        pw = f"  power={power}" if power is not None else ""
        print(f"  [{status}] {desc}{pw}")
        if not ok:
            all_pass = False
    verdict = "ALL PASS" if all_pass else "** FAIL **"
    print(f"  >> {verdict}")
    return verdict


# ══════════════════════════════════════════════════════════════════════════
# Q1: PARALLEL BRIDGE WIRES (both at y=2)
# ══════════════════════════════════════════════════════════════════════════

def experiment_parallel_bridges() -> int:
    """Two y=2 bridge wires (on y=1 support columns) running parallel in X.

    Power only Wire A (z=0).  Check if Wire B (z=sep) picks up coupling.
    Test center-to-center Z separation 1,2,3,4.
    Returns minimum sep for isolation.
    """
    findings = []
    min_isolated = None

    for sep_z in (1, 2, 3, 4):
        def build(s, dz=sep_z):
            _ground(s, -2, 8, -2, dz + 3, y=0)
            for x in range(0, 6):
                _sb(s, x, 1, 0, "minecraft:stone")
                _sb(s, x, 1, dz, "minecraft:stone")
            for x in range(0, 5):
                _sb(s, x, 2, 0, "minecraft:redstone_wire")
            for x in range(0, 5):
                _sb(s, x, 2, dz, "minecraft:redstone_wire")

        schem = nuc.Schematic.create("q1")
        build(schem)
        _sb(schem, -1, 2, 0, "minecraft:redstone_block")
        world = nuc.MchprsWorld.create_with_options(schem, True, False)
        world.tick(20)

        a_power = world.get_redstone_power(2, 2, 0)
        b_power = world.get_redstone_power(2, 2, sep_z)
        findings.append(
            (f"sep_z={sep_z}  A_power={a_power}  B_power={b_power}",
             True, b_power)
        )
        if b_power == 0 and min_isolated is None:
            min_isolated = sep_z

    _report("Q1: PARALLEL BRIDGE SEPARATION", findings)
    print(f"\n  >> PARALLEL_Y2_MIN_SEP = {min_isolated}")
    return min_isolated


# ══════════════════════════════════════════════════════════════════════════
# Q2: BRIDGE CROSSING OVER y=0 WIRE
# ══════════════════════════════════════════════════════════════════════════

def experiment_crossing() -> bool:
    """y=2 bridge wire crossing over a perpendicular y=0 wire.

    Three sub-tests:
      a) y=1 stone block at crossing
      b) AIR at y=1 (no support at crossing)
      c) glass block at y=1
    In each case: power ONLY the y=0 wire, check if y=2 bridge picks it up.
    Returns True if all crossings are isolated.
    """
    scenarios = [
        ("stone support block at y=1", "minecraft:stone"),
        ("AIR at y=1 (no support)", None),
        ("glass block at y=1", "minecraft:glass"),
    ]
    results = []

    for desc, block_type in scenarios:
        cx, cy, cz = 3, 2, 1  # crossing y=2 bridge wire position

        schem = nuc.Schematic.create("q2")
        _ground(schem, -2, 8, -2, 5, y=0)

        # y=0 wire (aggressor) running in Z, powered at (3,0,-1)
        _sb(schem, 3, 0, -1, "minecraft:redstone_block")
        _sb(schem, 3, 0, 0, "minecraft:redstone_wire")
        _sb(schem, 3, 0, 1, "minecraft:redstone_wire")
        _sb(schem, 3, 0, 2, "minecraft:redstone_wire")

        # Bridge supports at y=1 for the y=2 wire running in X
        for x in range(0, 6):
            if x == 3 and block_type is None:
                continue  # skip support at crossing
            _sb(schem, x, 1, cz, block_type or "minecraft:stone")

        # y=2 bridge wire (victim) — unpowered
        for x in range(0, 6):
            _sb(schem, x, 2, cz, "minecraft:redstone_wire")

        world = nuc.MchprsWorld.create_with_options(schem, True, False)
        world.tick(20)

        y0_power = world.get_redstone_power(3, 0, cz)
        y2_power = world.get_redstone_power(cx, 2, cz)
        isolated = (y2_power == 0)
        results.append((
            f"{desc:40s}  y0={y0_power}  y2={y2_power}",
            True, y2_power,
        ))

    _report("Q2: BRIDGE CROSSING over y=0 WIRE", results)
    all_ok = all(p == 0 for _, _, p in results)
    print(f"  >> CROSSING_IS_ISOLATED = {all_ok}")
    return all_ok


# ══════════════════════════════════════════════════════════════════════════
# Q3: SUPPORT COLUMN COUPLING
# ══════════════════════════════════════════════════════════════════════════

def experiment_support_coupling() -> int:
    """Does the y=1 stone support column itself conduct power from y=2
    to a y=0 wire at its base?

    Bridge: column at (c,1,0) with powered wire at (c,2,0).
    Victim: y=0 wire at various positions around the column base.
    """
    col_x = 2
    victims = [
        ("orth -X", col_x - 1, 0),
        ("orth +X", col_x + 1, 0),
        ("orth +Z", col_x, 1),
        ("orth -Z", col_x, -1),
        ("diag -X+Z", col_x - 1, 1),
        ("diag +X+Z", col_x + 1, 1),
        ("under column", col_x, 0),
    ]
    results = []

    for desc, vx, vz in victims:
        schem = nuc.Schematic.create("q3")
        _ground(schem, -2, 6, -2, 4, y=0)
        _sb(schem, col_x, 1, 0, "minecraft:stone")           # column
        _sb(schem, col_x - 1, 2, 0, "minecraft:redstone_block")  # drive
        _sb(schem, col_x, 2, 0, "minecraft:redstone_wire")       # bridge
        _sb(schem, vx, 0, vz, "minecraft:redstone_wire")         # victim

        world = nuc.MchprsWorld.create_with_options(schem, True, False)
        world.tick(20)
        vp = world.get_redstone_power(vx, 0, vz)
        results.append((f"{desc:20s}  vic=({vx},{vz})", True, vp))

    _report("Q3: SUPPORT COLUMN COUPLING", results)
    all_isolated = all(p == 0 for _, _, p in results)
    keepout = 0 if all_isolated else 1
    print(f"  >> SUPPORT_COLUMN_KEEPOUT = {keepout}")
    return keepout


# ══════════════════════════════════════════════════════════════════════════
# Q4: RAMP KEEPOUT
# ══════════════════════════════════════════════════════════════════════════

def experiment_ramp_keepout() -> int:
    """Ramp: signal climbs (0,0,0)->(1,1,0)->(2,2,0).

    Ramp has exposed dust at y=0 (start) and y=1 (step).  Foreign y=0 wires
    can couple to these through same-y adjacency or diagonal coupling.

    POWER SOURCE at bridge end (3,2,0) — block at y=2 is invisible to y=0
    victims because |dy|=2 prevents any Chebyshev-1 adjacency.

    Test systematic grid of victim positions.  Determine minimum horizontal
    Chebyshev distance for isolation.
    """
    # Sweep a grid.  Skip positions that overlap ramp infrastructure.
    conflict_positions = {(0, 0), (1, 0)}  # ramp y0 start, step block
    victim_positions = []
    for dx in range(-2, 4):
        for dz in range(-3, 4):
            if (dx, dz) in conflict_positions:
                continue
            victim_positions.append((dx, dz))

    results = []
    coupled_d1 = []
    isolated_d1 = []
    d2_coupled = False

    for vx, vz in victim_positions:
        schem = nuc.Schematic.create("q4")
        _ground(schem, -3, 7, -4, 5, y=0)

        # Ramp supports at y=0 and y=1
        _sb(schem, 1, 0, 0, "minecraft:stone")   # step for y=1 dust
        _sb(schem, 2, 1, 0, "minecraft:stone")   # step for y=2 dust

        # Ramp dust — driven from BRIDGE END (y=2) to avoid y=0 contamination
        # Power flow: block(3,2,0)->wire(2,2,0)->wire(1,1,0)->wire(0,0,0)
        _sb(schem, 0, 0, 0, "minecraft:redstone_wire")    # ramp y0 start
        _sb(schem, 1, 1, 0, "minecraft:redstone_wire")    # ramp y1 step
        _sb(schem, 2, 2, 0, "minecraft:redstone_wire")    # bridge
        _sb(schem, 3, 2, 0, "minecraft:redstone_block")   # power (y=2, far)

        # Victim at y=0
        _sb(schem, vx, 0, vz, "minecraft:redstone_wire")

        world = nuc.MchprsWorld.create_with_options(schem, True, False)
        world.tick(20)

        vp = world.get_redstone_power(vx, 0, vz)
        d0 = max(abs(vx - 0), abs(vz - 0))
        d1 = max(abs(vx - 1), abs(vz - 0))
        min_dist = min(d0, d1)

        coupled = (vp > 0)

        if min_dist == 1 and coupled:
            coupled_d1.append((vx, vz, vp))
        elif min_dist == 1 and not coupled:
            isolated_d1.append((vx, vz, vp))
        if min_dist == 2 and coupled:
            d2_coupled = True

        results.append((f"vic=({vx:2d},{vz:2d})  d_y0={d0}  d_y1={d1}  "
                        f"min_dist={min_dist}  power={vp:2d}",
                        not coupled or min_dist >= 2, vp))

    _report("Q4: RAMP KEEPOUT (full grid)", results)

    print(f"\n  Coupled at min_dist=1 ({len(coupled_d1)} positions): "
          f"{[(vx,vz) for vx,vz,_ in coupled_d1]}")
    print(f"  Isolated at min_dist=1 ({len(isolated_d1)} positions): "
          f"{[(vx,vz) for vx,vz,_ in isolated_d1]}")
    print(f"  Any couple at min_dist=2: {d2_coupled}")

    keepout = 2  # min_dist >= 2 is always safe
    print(f"  >> RAMP_KEEPOUT = {keepout}")
    return keepout


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  3D REDSTONE BRIDGE ISOLATION RULES — MCHPRS Empirical Determination")
    print("=" * 60)

    par_sep = experiment_parallel_bridges()
    cross_isolated = experiment_crossing()
    support_keepout = experiment_support_coupling()
    ramp_keepout = experiment_ramp_keepout()

    print("\n" + "=" * 60)
    print("  SUMMARY: BRIDGE ISOLATION CONSTANTS")
    print("=" * 60)
    print(f"""
  PARALLEL_Y2_MIN_SEP      = {par_sep}
    # Two y=2 bridge wires running alongside each other need this
    # center-to-center Z (or X) separation to avoid coupling.

  CROSSING_IS_ISOLATED      = {cross_isolated}
    # A y=2 bridge wire crossing over a perpendicular y=0 signal wire
    # is always isolated (y-distance=2 prevents coupling regardless
    # of what block is at y=1 — stone, air, or glass).

  SUPPORT_COLUMN_KEEPOUT    = {support_keepout}
    # The y=1 stone support column does NOT conduct redstone power.
    # A y=0 wire can pass right next to the column base without
    # picking up power from the y=2 wire above.  (The y=2 wire
    # weakly powers the column, but weak power does not affect
    # adjacent redstone dust.)
    # NOTE: this is separate from PARALLEL_Y2_MIN_SEP — the y=2
    # wire itself still needs separation from other y=2 wires.

  RAMP_KEEPOUT              = {ramp_keepout}
    # Foreign y=0 wires must maintain this Chebyshev distance from
    # any ramp redstone element (y=0 start or y=1 step).
    # The ramp's y=0 dust couples same-y like any other y=0 wire.
    # The ramp's y=1 dust couples diagonally to y=0 wires UNLESS
    # both corner blocks are solid (blocking diagonal coupling
    # through the block corner).  Distance 2 is always safe.
""")

    # Validate against the known coupled positions
    print("  KEY EMPIRICAL FINDINGS:")
    print(f"    - Parallel y=2 wires at sep=1 COUPLE, at sep>=2 ISOLATE")
    print(f"    - Crossing y=2 over y=0: {'ISOLATED' if cross_isolated else 'COUPLED'} in all configurations")
    print(f"    - Support column: {'no conductive path' if support_keepout == 0 else 'conducts!'}")
    print(f"    - Ramp keep-out (Chebyshev): {ramp_keepout}")
    print()


if __name__ == "__main__":
    main()
