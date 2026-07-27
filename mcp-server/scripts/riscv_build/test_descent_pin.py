"""
test_descent_pin.py — MCHPRS: verify a y=2 bridge descends and drives a cell
input pin (repeater[facing=west]) correctly. Find the exact voxel geometry.

A cell input pin is repeater[facing=west] at (px,0,pz): it reads its EAST-back?
No — facing=west means it conducts toward +x (east) i.e. drives the gate to its
east, and reads input from its WEST neighbor (px-1). So we must land y0 dust at
(px-1,0,pz).

Scene: an isolated NOT cell whose input pin is fed by a descending bridge.
Drive the bridge source, read the NOT output. Expect inversion.
"""
import sys, os
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"
WT = "minecraft:redstone_wall_torch[facing=east]"

def build(drive):
    sc = nuc.Schematic.create("d")
    B = sc.set_block_from_string
    # floor
    for x in range(0, 20):
        for z in range(0, 6):
            B(x, -1, z, S)
    # NOT cell at origin (10,0,2): in pin (10,0,2)=rep[facing=west], mount(11), torch(12), out(13)
    px, pz = 10, 2
    B(px, 0, pz, rep("west"))   # input pin
    B(px+1, 0, pz, S); B(px+2, 0, pz, WT); B(px+3, 0, pz, W)  # NOT body -> out at (13,0,2)
    # bridge: source dust at (0,0,2) driven from (-? ) -> climb -> y2 run -> descend into (px-1,0,pz)
    # climb (Agent A) flow +x
    sx = 0
    B(sx, 0, pz, W)                       # source dust (driven)
    B(sx+1, 0, pz, rep("west"))
    B(sx+2, 0, pz, S); B(sx+2, 1, pz, W)
    B(sx+3, 1, pz, S); B(sx+3, 2, pz, W)
    # y2 run sx+4 .. px-3, support at y1
    for x in range(sx+4, px-2):
        B(x, 1, pz, S); B(x, 2, pz, W)
    # descend: y2 dust @ (px-3? ) -> we ended run at px-3. Now step down:
    # Agent A descent: y2@(gx-2) -> block@y0(top y1)+dust@y1 @(gx-1) -> y0 dust@gx.
    # We want y0 dust to land at (px-1,pz) feeding the pin at (px,pz).
    # So gx = px-1 (final y0), gx-1 = px-2 (descend block+dust y1), gx-2 = px-3 (y2 top).
    # ensure y2 dust at (px-3,pz):
    B(px-3, 1, pz, S); B(px-3, 2, pz, W)
    # descend block at (px-2,pz): block y0, dust y1
    B(px-2, 0, pz, S); B(px-2, 1, pz, W)
    # final y0 dust at (px-1,pz) feeding the west-facing pin at (px,pz)
    B(px-1, 0, pz, W)
    # driver
    B(sx-0, 0, pz, RB if drive else W)  # overwrite source dust with block to drive
    if drive:
        B(sx, 0, pz, RB)
    else:
        B(sx, 0, pz, W)
        # need something to drive it low: leave as wire (0)
    return sc, (px+3, 0, pz)  # probe = NOT output

for drive in (0, 1):
    sc, probe = build(drive)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(20)
    out = w.get_redstone_power(*probe)
    exp = 0 if drive else 1   # NOT: out = !in
    print(f"drive={drive} NOTout={out} expect={exp} {'OK' if (out>0)==(exp>0) else 'X'}")
