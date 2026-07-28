"""
test_via_pin.py — MCHPRS: pin down the via-tower <-> cell-pin handoff.

The routed circuit connects gate OUTPUT (y=0 dust) -> via UP to trunk -> via
DOWN -> gate INPUT (repeater[facing=west] at y=0). We must know:
  1. Does a standing-torch tower actually carry the signal up N levels, and with
     what parity (each torch inverts)?
  2. How does the tower BOTTOM connect to a y=0 dust source?
  3. How does the tower TOP connect to a horizontal y=2/y4 trunk dust?
  4. How does the descent tower BOTTOM feed a repeater[facing=west] input pin?

We build minimal scenes and read power/lit to establish the exact geometry +
parity, then feed that back into emit_full.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleation as nuc
S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
ST = "minecraft:redstone_torch"       # standing torch
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1+1):
        for z in range(z0, z1+1):
            B(x, y, z, S)

def probe(sc, x, y, z):
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(30)
    return w.get_redstone_power(x, y, z)

# T1: standing-torch tower — how does signal ENTER from a y=0 dust, and what's
# at the top? Build: y0 dust driven -> tower up 4 levels -> read each torch level.
def T1(drive):
    sc = nuc.Schematic.create("t1"); B = sc.set_block_from_string
    flr(B, -2, 6, -2, 2)
    z = 0
    # drive a y0 dust at x=0
    B(-1, 0, z, RB if drive else "minecraft:air")
    B(0, 0, z, W)
    # tower at x=0: the y0 dust sits ON the floor; to go up we need the dust to
    # power a block, torch on top. Standard: dust -> adjacent block gets powered
    # -> torch on block is OFF. That's an inverter, not a riser.
    # A proper UP riser: block under dust at x=0 is floor. Put block at (0,0,z)?
    # occupied by dust. Use the verified repeater-into-block riser instead:
    #   dust(0) -> repeater(1,facing=west,out east) -> block(2) strongly powered
    #   -> dust on top(2,y1) -> block(3,y1)+dust(3,y2) ...
    B(1, 0, z, rep("west"))          # repeater output east
    B(2, 0, z, S); B(2, 1, z, W)     # block powered by repeater, dust on top (y1)
    B(3, 1, z, S); B(3, 2, z, W)     # climb to y2
    B(4, 2, z, S); B(4, 3, z, W)     # climb to y3
    return sc, [("y1", 2, 1, z), ("y2", 3, 2, z), ("y3", 4, 3, z)]

# T2: full chain — source dust -> riser up to y2 -> trunk dust -> descend to y0
# -> feed a NOT cell's input pin (repeater[facing=west]) -> read NOT output.
# Descend = mirror: dust y2 -> block y1 + dust y2 above? Use descending staircase
# (verified see-below): y2 dust steps down via block+dust each -1 layer.
def T2(drive):
    sc = nuc.Schematic.create("t2"); B = sc.set_block_from_string
    flr(B, -2, 24, -2, 2)
    z = 0
    # source y0 dust driven
    B(-1, 0, z, RB if drive else "minecraft:air")
    B(0, 0, z, W)
    # riser up to y2 (repeater-into-block, non-inverting)
    B(1, 0, z, rep("west")); B(2, 0, z, S); B(2, 1, z, W); B(3, 1, z, S); B(3, 2, z, W)
    # trunk run on y2 from x=4..10 (supports below)
    for x in range(4, 11):
        B(x, 1, z, S); B(x, 2, z, W)
    # descend y2 -> y0 via +x staircase (see-below rule): each +x drop 1 layer
    B(11, 1, z, S); B(11, 2, z, W)     # y2
    B(12, 0, z, S); B(12, 1, z, W)     # y1 (block at y0, dust y1)
    B(13, 0, z, W)                     # y0 dust
    # feed NOT cell: input pin repeater[facing=west] at (15,0,z); the y0 dust at
    # (14) feeds it from west
    B(14, 0, z, W)
    B(15, 0, z, rep("west"))           # NOT input pin (reads from west=14)
    B(16, 0, z, S); B(17, 0, z, "minecraft:redstone_wall_torch[facing=east]")  # NOT body
    B(18, 0, z, W)                     # NOT output
    return sc, (18, 0, z)              # probe NOT output

# T3: PURELY VERTICAL tower (1x1 footprint, no +x spread) — can it carry signal
# up and connect to a repeater pin? Test standing-torch tower with EVEN torches.
def T3(drive, torches=2):
    sc = nuc.Schematic.create("t3"); B = sc.set_block_from_string
    flr(B, -2, 6, -2, 2)
    z = 0; x = 2
    # drive from west into a repeater that feeds the tower base block
    B(x-3, 0, z, RB if drive else "minecraft:air")
    B(x-2, 0, z, W)
    B(x-1, 0, z, rep("west"))       # repeater -> strongly powers base block
    B(x, 0, z, S)                   # base block
    # vertical standing-torch tower: torch on top of block, block on torch, ...
    y = 0; probes = []
    for i in range(torches):
        B(x, y+1, z, ST)            # standing torch (inverts vs block below)
        B(x, y+2, z, S)             # block above torch (powered when torch lit)
        probes.append((f"torch{i}@y{y+1}", x, y+1, z))
        y += 2
    return sc, probes

if __name__ == "__main__":
    print("=== T3: pure-vertical standing-torch tower ===")
    for d in (0, 1):
        sc, probes = T3(d, torches=2)
        w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(30)
        print(f"  drive={d}: {{{', '.join(f'{n}={1 if w.is_lit(x,y,zz) else 0}' for n,x,y,zz in probes)}}}")
    print("=== T1: repeater-into-block riser ===")
    for d in (0, 1):
        sc, probes = T1(d)
        w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(30)
        print(f"  drive={d}: {{{', '.join(f'{n}={w.get_redstone_power(x,y,zz)}' for n,x,y,zz in probes)}}}")
    print("=== T2: source -> riser -> trunk -> descend -> NOT pin -> output ===")
    print("    (chain is non-inverting to the pin; NOT inverts => out = ~drive)")
    for d in (0, 1):
        sc, probe_pos = T2(d)
        w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(40)
        out = w.get_redstone_power(*probe_pos)
        exp = 0 if d else 1
        print(f"  drive={d}: NOT_out={out} expect={exp} {'OK' if (out>0)==(exp>0) else 'X'}")
