"""
test_feed_glass_real.py — the decisive geometry for the competition problem, with
REALISTIC cell placement (not an idealized slab):

A 2-input gate at x=42 has:
    A feed at (41, z)   driven by net A
    B feed at (41, z+2) driven by net B
    the cell body fills (42, z..z+2)

With STONE floor, net A's wire at the feed strongly powers the floor below it,
which then powers the floor cell under (41, z+1) — and B's feed at (41, z+2)
sits 2 cells away, so the leak path is:
    A wire (41,z) -> stone floor (41,z) -> stone floor (41,z+1) -> ... ?

With a GLASS floor the whole horizontal floor path dies. But the floor is stone
in the final build (cells need it). The question is whether the ROUTED wires'
see-below coupling (one level down, one cell across, through a STONE floor)
actually couples two feeds 2 apart in z.

Build the real gate cell on a stone floor, feed A and B from the west at z and
z+2, and drive A while reading B. Try floor=stone vs floor=glass.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
import cell_library as clib

S = "minecraft:stone"; W = "minecraft:redstone_wire"
GLASS = "minecraft:glass"
RB = "minecraft:redstone_block"


def run(floor_material, drive, ticks=40):
    sc = nuc.Schematic.create(f"f_{floor_material[-5:]}_{drive}")
    B = sc.set_block_from_string
    for x in range(-8, 12):
        for z in range(-3, 8):
            B(x, -1, z, floor_material)
    # the real NAND cell at origin (42,0,19) -> local (0,0,19)
    clib.get("NAND").emit(sc, 0, 0, 19)
    # feed A (drives A@(0,0,19)) and B (drives B@(0,0,21)) from the west
    B(-3, 0, 19, RB if drive else "minecraft:air")
    B(-2, 0, 19, W); B(-1, 0, 19, W)        # A feed, cell (41,19)
    B(-3, 0, 21, RB if drive else "minecraft:air")
    B(-2, 0, 21, W); B(-1, 0, 21, W)        # B feed, cell (41,21)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    out = w.get_redstone_power(8, 0, 20)    # NAND output at (8,0,20)? Q=(10,0,1)+19
    q = clib.get("NAND").outputs["Q"]
    return w.get_redstone_power(q[0], q[1], q[2] + 19)


if __name__ == "__main__":
    print("real NAND cell, A@z=19 B@z=21, driving A, reading Q:")
    for fm in (S, GLASS):
        for drive in (0, 1):
            q = run(fm, drive)
            print(f"  floor={fm.split(':')[1]:5s} drive_A={drive}: Q={q}")
        print()
    print("Q(0) vs Q(1) tells us whether B leaked into A's NAND input.")
    print("If Q is the same for drive 0 and 1, A cannot reach the gate.")
