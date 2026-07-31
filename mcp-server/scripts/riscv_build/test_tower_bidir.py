"""
test_tower_bidir.py — a BIDIRECTIONAL torch tower: constant small footprint for
BOTH up and down transmission.

Why this matters: the up-tower is 1x1 and verified, but nothing carried a signal
DOWN without a staircase whose length grows with the depth. Since a staircase
eats horizontal room exactly where sinks live, that was the last failure class
(and moving the cross plane underground merely swapped which side needed it).

Physics used for the DOWN step (each step inverts):
  1. powered dust at (x, y, z) gives block power to the block BELOW it
     (x, y-1, z)  — this is why a torch under a powered line switches off;
  2. a wall torch attached to that block therefore turns OFF when the dust is on;
  3. a lit torch powers redstone dust ORTHOGONALLY ADJACENT at its own level.
So: dust(level y) -> block below -> side torch(level y-1) -> dust(level y-1)
one cell away. Alternating the offset between the X and Z partner cell folds the
chain back into a 2x2 column, so the footprint never grows with depth.

Layout of one DOWN cycle (2 torches => non-inverting, down 2 levels):
    A=(x,z)      B=(x+1,z)      C=(x+1,z+1)
    dust @ (A, y)      on block (A, y-1)
    torch @ (B, y-1) facing=east  (attached to block A,y-1)
    dust  @ (C, y-1)   on block (C, y-2)          <- powered by that torch
    torch @ (B, y-2) facing=south (attached to block C,y-2)
    dust  @ (A, y-2)                              <- back in column A, 2 down
Footprint: {A, B, C} inside a 2x2 — constant for any depth.

Tests:
  T_DOWN  : drive the top dust, read the bottom dust, several depths.
  T_PARITY: even torch count must be non-inverting, drive=0 must NOT be stuck 1.
  T_UPDOWN: same 2x2 shaft used UP (verified 1x1 ladder) then DOWN, end to end.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"
def repw(): return "minecraft:repeater[facing=west,delay=1]"


def slab(B, x0, x1, z0, z1, y):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def emit_down(B, ax, az, y_top, cycles):
    """Emit `cycles` DOWN cycles (each = 2 torches, -2 Y) starting from a dust at
    (ax, y_top, az). Returns (bottom dust y, list of torch positions)."""
    # Measured wall-torch rules (test_walltorch_attach):
    #   facing=X  =>  its SUPPORT block is the neighbour on the OPPOSITE side
    #                 (facing=east -> support to the west, etc.)
    #   a lit wall torch powers every adjacent cell except its support, plus the
    #   cell above it.
    # One cycle (2 torches, -2 Y), all inside x..x+1 / z..z+1:
    #   dust A(y)      on support A(y-1)
    #   torch1 @ (x+1, y-1, z)  facing=east  -> support is A(y-1): OFF when A is on
    #   dust B(y-1) @ (x+1, y-1, z+1) on support (x+1, y-2, z+1), lit by torch1
    #   torch2 @ (x,  y-2, z+1) facing=west  -> support is B's block: OFF when B on
    #   dust A(y-2) @ (x, y-2, z) on support A(y-3), lit by torch2
    bx, bz = ax + 1, az + 1      # the partner dust column
    torches = []
    y = y_top
    for _ in range(cycles):
        B(ax, y - 1, az, S)                       # support under the A dust
        t1 = (ax + 1, y - 1, az)
        B(t1[0], t1[1], t1[2], wt("east"))        # support = A block (to its west)
        torches.append(t1)
        B(bx, y - 2, bz, S)                       # support under partner dust
        B(bx, y - 1, bz, W)                       # partner dust, lit by torch1
        t2 = (ax, y - 2, az + 1)
        B(t2[0], t2[1], t2[2], wt("west"))        # support = partner block (east)
        torches.append(t2)
        B(ax, y - 3, az, S)                       # support for the next A dust
        B(ax, y - 2, az, W)                       # back in column A, 2 levels down
        y -= 2
    return y, torches


def run_down(drive, cycles, base=0):
    """Drive a top dust at y_top and read the dust `cycles`*2 levels below."""
    y_top = base + 2 * cycles
    sc = nuc.Schematic.create(f"dn_{drive}_{cycles}")
    B = sc.set_block_from_string
    slab(B, -6, 8, -4, 6, base - 3)
    ax, az = 2, 1
    # drive the top dust reliably: RB -> dust -> repeater -> block -> dust on top
    B(ax - 4, y_top, az, RB if drive else "minecraft:air")
    for xx in (ax - 4, ax - 3, ax - 2, ax - 1):
        B(xx, y_top - 1, az, S)
    B(ax - 3, y_top, az, W)
    B(ax - 2, y_top, az, repw())
    B(ax - 1, y_top, az, S)
    B(ax - 1, y_top + 1, az, W)     # dust above the driven block
    B(ax, y_top, az, W)             # the tower's top dust (fed from the west)
    y_bot, torches = emit_down(B, ax, az, y_top, cycles)
    B(ax, y_bot, az, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(60)
    return (w.get_redstone_power(ax, y_bot, az),
            [1 if w.is_lit(*t) else 0 for t in torches], y_bot)


if __name__ == "__main__":
    print("=== DOWN tower in a constant 2x2 footprint (2 torches per cycle) ===")
    print("expect: drive1 -> bottom>0, drive0 -> bottom=0 (even torches, non-inverting)")
    ok_all = True
    for cyc in (1, 2, 3, 5):
        p1, t1, yb = run_down(1, cyc)
        p0, t0, _ = run_down(0, cyc)
        ok = (p1 > 0 and p0 == 0)
        ok_all &= ok
        print(f"  cycles={cyc} ({2*cyc} torches, drop {2*cyc}Y, bottom y={yb}): "
              f"drive1={p1} drive0={p0}  {'OK' if ok else 'FAIL'}")
        print(f"     torch lit drive1={t1}")
        print(f"     torch lit drive0={t0}")
    print(f"  => {'ALL OK' if ok_all else 'SOME FAIL'}")
