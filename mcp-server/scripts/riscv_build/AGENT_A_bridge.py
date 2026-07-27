"""
AGENT_A_bridge.py — Redstone bridge gadget crossing over an obstacle wire.

Builds a wire that climbs 2 blocks, runs over a perpendicular obstacle with a
1-block isolating gap (solid separator), and descends back to ground level.
MCHPRS-verified: 4/4 net independence.
"""

from __future__ import annotations
import sys
import os
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "redstone3d"))
import nucleation as nuc

# A typed placement tuple: ("dust", x, y, z)
#                         ("rep", x, y, z, facing)
#                         ("block", x, y, z)   — solid block (mount for dust on top)
#                         ("support", x, y, z) — solid block below elevated dust
Placement = Tuple


def make_bridge(
    start_xz: Tuple[int, int],
    goal_xz: Tuple[int, int],
    base_y: int,
    net: str,
) -> List[Placement]:
    """Build a bridge over a perpendicular obstacle wire.

    The bridge starts from an existing source wire at start_xz (y=base_y)
    and delivers signal to goal_xz (y=base_y).  It climbs 2 blocks, runs
    horizontally at y=base_y+2 with support blocks at y=base_y+1, then
    descends.  The 1-block gap (y=base_y+1 solid block above the obstacle
    at y=base_y) isolates the two nets.

    Only +x (eastward) straight-line routing is supported.

    Returns a list of Placement tuples that the caller places into the world.
    """
    sx, sz = start_xz
    gx, gz = goal_xz

    assert gx > sx, "Only +x (eastward) routing is currently supported"
    assert sz == gz, "Only straight-line routing is supported (same z)"

    min_required = gx - sx
    assert min_required >= 7, (
        f"Bridge requires at least 7 blocks separation (got {min_required}): "
        "1 repeater + 2 climb + 1 run + 1 descent block + 1 descent dust + 1 goal"
    )

    placements: List[Placement] = []

    # -- Climb: refresh, then staircase up 2 blocks ---------------------------
    # Repeater at +1 from source — facing=west so signal flows east (+x)
    placements.append(("rep", sx + 1, base_y, sz, "west"))

    # Climb stage 1: solid block at base_y, dust on top at base_y+1
    placements.append(("block", sx + 2, base_y, sz))
    placements.append(("dust", sx + 2, base_y + 1, sz))

    # Climb stage 2: solid block at base_y+1, dust on top at base_y+2
    placements.append(("block", sx + 3, base_y + 1, sz))
    placements.append(("dust", sx + 3, base_y + 2, sz))

    # -- Elevated run at base_y+2 with support blocks at base_y+1 ------------
    # Run from sx+4 to gx-2 (inclusive), each dust has a block below
    for rx in range(sx + 4, gx - 1):
        placements.append(("support", rx, base_y + 1, sz))
        placements.append(("dust", rx, base_y + 2, sz))

    # -- Descend back to base_y ----------------------------------------------
    # Descent step-down: block at base_y (top face at base_y+1) + dust on top
    placements.append(("block", gx - 1, base_y, sz))
    placements.append(("dust", gx - 1, base_y + 1, sz))

    # Final ground-level dust at the goal position
    placements.append(("dust", gx, base_y, sz))

    return placements


# ---------------------------------------------------------------------------
# Helper: place bridge placements into a schematic
# ---------------------------------------------------------------------------

def place_placements(schem: nuc.Schematic, placements: List[Placement]) -> None:
    """Place every typed placement into the schematic."""
    for p in placements:
        t = p[0]
        if t == "rep":
            _, x, y, z, facing = p
            blk = f"minecraft:repeater[facing={facing},delay=1]"
        elif t in ("dust",):
            _, x, y, z = p
            blk = "minecraft:redstone_wire"
        elif t in ("block", "support"):
            _, x, y, z = p
            blk = "minecraft:stone"
        else:
            raise ValueError(f"Unknown placement type: {t}")
        schem.set_block_from_string(x, y, z, blk)


def set_injection(schem: nuc.Schematic, x: int, y: int, z: int, value: int) -> None:
    """Place redstone_block for 1, air for 0."""
    schem.set_block_from_string(
        x, y, z,
        "minecraft:redstone_block" if value else "minecraft:air",
    )


def report(results: List[dict]) -> bool:
    """Print test results; return True iff all match."""
    passed = sum(1 for r in results if r["match"])
    total = len(results)
    ok = passed == total
    print(f"  {passed}/{total} -- {'PASS' if ok else 'FAIL'}")
    for r in results:
        inp = " ".join(f"{k}={v}" for k, v in r["inputs"].items())
        exp = " ".join(f"{k}={v}" for k, v in r["expected"].items())
        act = " ".join(f"{k}={v}" for k, v in r["actual"].items())
        tag = "OK" if r["match"] else "X"
        print(f"    [{tag}]  {inp}  exp({exp})  got({act})")
    return ok


# ---------------------------------------------------------------------------
# Self-test: build scene, simulate 4 vectors, verify independence
# ---------------------------------------------------------------------------

def build_scene(schem: nuc.Schematic, bridge_input: int, obstacle_input: int) -> None:
    """Build the full test scene with bridge and perpendicular obstacle."""
    # Stone floor at y=-1 covering the entire area
    for fx in range(2, 20):
        for fz in range(-2, 12):
            schem.set_block_from_string(fx, -1, fz, "minecraft:stone")

    # -- Obstacle net (runs in +z at x=10, y=0) --
    # Injection at (10, 0, 0): powers the wire at (10, 0, 1)
    set_injection(schem, 10, 0, 0, obstacle_input)
    for oz in range(1, 8):
        schem.set_block_from_string(10, 0, oz, "minecraft:redstone_wire")
    # Lamp reads the net at (10, 0, 8)
    schem.set_block_from_string(10, 0, 8, "minecraft:redstone_lamp")

    # -- Bridge net (runs in +x from (5,4) to (15,4)) --
    # Injection at (4, 0, 4)
    set_injection(schem, 4, 0, 4, bridge_input)
    # Source wire connects injection to the bridge's repeater
    schem.set_block_from_string(5, 0, 4, "minecraft:redstone_wire")
    # Build and place the bridge
    placements = make_bridge((5, 4), (15, 4), 0, "bridge")
    place_placements(schem, placements)
    # Output lamp at (16, 0, 4) reads the bridge's goal
    schem.set_block_from_string(16, 0, 4, "minecraft:redstone_lamp")


def self_test() -> bool:
    """Test all 4 combinations of (bridge, obstacle)."""
    print("=" * 60)
    print("Bridge self-test: 4-way net independence")
    print("=" * 60)

    results = []
    for bi in (0, 1):
        for oi in (0, 1):
            schem = nuc.Schematic.create("bridge_test")
            build_scene(schem, bi, oi)
            world = nuc.MchprsWorld.create_with_options(schem, True, False)
            world.tick(24)  # generous settle time

            b_lamp = 1 if world.is_lit(16, 0, 4) else 0
            o_lamp = 1 if world.is_lit(10, 0, 8) else 0

            results.append({
                "inputs": {"bridge": bi, "obstacle": oi},
                "actual": {"bridge": b_lamp, "obstacle": o_lamp},
                "expected": {"bridge": bi, "obstacle": oi},
                "match": b_lamp == bi and o_lamp == oi,
            })

    ok = report(results)
    print()
    verdict = "4/4 PASS -- nets are independent" if ok else "FAILED -- nets interfere!"
    print(f"Overall: {verdict}")
    return ok


# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====
#  Utility: dump scene layout for debugging
# ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== ===== =====

def dump_placements(placements: List[Placement]) -> None:
    """Print human-readable placement list."""
    for p in placements:
        t = p[0]
        if t == "rep":
            _, x, y, z, f = p
            print(f"  repeater [{f}]  @ ({x}, {y}, {z})  # signal flows opposite facing")
        elif t in ("dust", "block", "support"):
            _, x, y, z = p
            blk = {"dust": "wire", "block": "stone", "support": "stone(support)"}[t]
            print(f"  {blk:16s}  @ ({x}, {y}, {z})")


if __name__ == "__main__":
    # Print the bridge layout
    print("\nBridge layout for (5,4) -> (15,4):")
    print("-" * 40)
    pl = make_bridge((5, 4), (15, 4), 0, "bridge")
    dump_placements(pl)
    print()
    print(f"Total: {len(pl)} placements")

    print()

    ok = self_test()
    sys.exit(0 if ok else 1)
