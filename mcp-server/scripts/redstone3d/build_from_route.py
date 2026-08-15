"""
build_from_route.py — turn a BuildableRouter result into blocks, for both
MCHPRS simulation and in-game export. Shared by the MCHPRS validator and the
bot exporter so we test EXACTLY what we build.
"""
from __future__ import annotations
from typing import Dict, Callable
from placer import Placement
from route_buildable import BuildResult

W = "minecraft:redstone_wire"
S = "minecraft:stone"
RBLOCK = "minecraft:redstone_block"
# NON-CONDUCTIVE support. Measured (riscv_build/test_insulators.py): glass,
# stained glass, smooth_stone_slab and glowstone all carry a redstone wire
# normally yet CANNOT be powered, so the see-below / ramp coupling through the
# support block disappears:
#     stone support : victim one level down and one across reads 12  (leaks)
#     glass support : victim reads 0                                 (isolated)
# And with glass supports, two feed cells two apart in z with the middle cell
# empty are fully isolated (test_glass_parallel G4), which is exactly the
# geometry that forced the huge keep-outs. Towers still need a POWERABLE block
# for their base and rungs, so only the passive supports become glass.
GLASS = "minecraft:glass"


def emit_blocks(setter: Callable[[int, int, int, str], None],
                pl: Placement, res: BuildResult,
                input_values: Dict[str, int]):
    """Write all blocks via setter(x,y,z,blockstate). Order: floor, supports,
    cells, wires, repeaters, PI injection. `setter` may be a Schematic method
    or a recorder."""
    # 1. floor slab covering the placement + margins + raised-wire supports
    mn, mx = pl.bounds
    xs = [p[0] for w in res.wires.values() for p in w] + [mn[0], mx[0]]
    zs = [p[2] for w in res.wires.values() for p in w] + [mn[2], mx[2]]
    fx0, fx1 = min(xs) - 2, max(xs) + 2
    fz0, fz1 = min(zs) - 2, max(zs) + 2
    floor_y = mn[1] - 1
    # The floor stays STONE. Making it glass was measured to be worse
    # (both-correct 16/40 -> 10/40, cout went from moving to stuck): the gate
    # cells rely on the floor for strong power — a wall torch's mount and the
    # repeater input pins sit on it — so a non-conductive floor breaks the cells
    # themselves. Only the RAISED passive supports become glass.
    for x in range(fx0, fx1 + 1):
        for z in range(fz0, fz1 + 1):
            setter(x, floor_y, z, S)

    # 2. support blocks under raised wires. PASSIVE supports become glass so they
    # cannot be powered (killing the see-below/ramp coupling); the CROSS-PLANE
    # supports and the tower rungs (power_blocks) must stay stone because a
    # staircase's first step and a down-tower's input read the dust THROUGH the
    # support's strong power (measured: glass cross support -> landing 0 in both
    # seam tests, while glass everywhere else keeps the truth table identical:
    # 16/40 both, c_ok=30 moving — patch_glass_seam).
    powered = getattr(res, "power_blocks", set())
    for (x, y, z) in res.supports:
        if y >= 2 or (x, y, z) in powered:
            setter(x, y, z, S)
        else:
            setter(x, y, z, GLASS)

    # 3. cells
    class _Adapter:
        def set_block_from_string(self, x, y, z, s):
            setter(int(x), int(y), int(z), s)
    ad = _Adapter()
    for pc in pl.placed.values():
        pc.cell.emit(ad, *pc.origin)

    # 4. wires
    for net, ws in res.wires.items():
        for (x, y, z) in ws:
            setter(x, y, z, W)

    # 4.4 output stubs: the placer publishes each net's source TWO cells east
    # of the real output pin with a repeater in between, so the source dust has
    # 3 escape lanes even under the 1-cell cell keep-out. Emit the repeater and
    # the source dust so the pin actually reaches the routed net.
    for (pin, rep, pub) in getattr(pl, "out_stubs", []):
        setter(rep[0], rep[1], rep[2],
               "minecraft:repeater[facing=west,delay=1]")
        setter(pub[0], pub[1], pub[2], W)

    # 4.5 standing torches (1x1 bridge tower rungs)
    for (x, y, z) in getattr(res, "torches", []):
        setter(x, y, z, "minecraft:redstone_torch")

    # 4.6 wall torches with explicit facing (2x2 down-tower rungs)
    for (pos, blk) in getattr(res, "wall_torches", []):
        setter(pos[0], pos[1], pos[2], blk)

    # 5. repeaters
    for net, reps in res.repeaters.items():
        for (pos, facing) in reps:
            setter(pos[0], pos[1], pos[2], f"minecraft:repeater[facing={facing},delay=1]")

    # 6. primary inputs: drive with a redstone_block WEST of the PI pos, PI pos =
    # wire. Only clear the injection cell when the value is 0 AND no routed wire
    # lives there — a net can legitimately route through (pos[0]-1); blanking it
    # used to sever that net (n6 lost its (-1,0,64) dust).
    routed_xyz = {p for ws in res.wires.values() for p in ws}
    for net, pos in pl.primary_inputs.items():
        val = input_values.get(net, 0)
        inj = (pos[0]-1, pos[1], pos[2])
        if val:
            setter(inj[0], inj[1], inj[2], RBLOCK)
        elif inj not in routed_xyz:
            setter(inj[0], inj[1], inj[2], "minecraft:air")
        setter(pos[0], pos[1], pos[2], W)
