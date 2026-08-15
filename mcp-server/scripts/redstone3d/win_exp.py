"""
win_exp.py — minimal MCHPRS experiments on repeater driving a NOT stage,
matching the cell library geometry exactly:

  dust(0,0,0) -> repeater[facing=west](1,0,0) -> stone(2,0,0)
  wall_torch[facing=east] on (3,0,0) -> dust(4,0,0)

Expected: input 1 -> torch OFF -> out 0 ; input 0 -> torch ON -> out 15.
Also probes get_signal_strength vs get_redstone_power on the stone.
"""
import nucleation as nuc


def build(w, inj: int):
    # floor
    for x in range(-1, 7):
        w.set_block_from_string(x, -1, 0, "minecraft:stone")
    w.set_block_from_string(0, 0, 0, "minecraft:redstone_wire")
    w.set_block_from_string(1, 0, 0, "minecraft:repeater[facing=west,delay=1]")
    w.set_block_from_string(2, 0, 0, "minecraft:stone")
    w.set_block_from_string(3, 0, 0, "minecraft:redstone_wall_torch[facing=east]")
    w.set_block_from_string(4, 0, 0, "minecraft:redstone_wire")
    # injection: redstone_block west of dust (strong power) / air
    if inj:
        w.set_block_from_string(-1, 0, 0, "minecraft:redstone_block")
    else:
        w.set_block_from_string(-1, 0, 0, "minecraft:air")


for inj in (0, 1):
    sc = nuc.Schematic.create("t")
    build(sc, inj)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(10)
    rp = w.get_redstone_power
    ss = w.get_signal_strength
    print(f"inj={inj}: dust0 rp={rp(0,0,0)} stone2 rp={rp(2,0,0)} "
          f"ss={ss(2,0,0)} torch3 ss={ss(3,0,0)} out4 rp={rp(4,0,0)}",
          flush=True)
