"""
test_via_down.py — the SINK-side via: signal must go DOWN from a trunk dust
(y_top) to a y0 dust, in a 1x1 footprint (no horizontal spread).

Why this matters: alu1 pins are all at y0. A net rises y0->trunk at the SOURCE
(torch tower, already verified up-driving), runs on the trunk, then must DROP
back to y0 at each SINK. The old drop_cells spread +x per level (short source).
The +z dust staircase (test_vertical V4) FAILED. We need a 1x1 DOWN gadget.

Candidates:
  DA: torch tower driven at the TOP (trunk dust powers block_top), read at bottom.
      A torch tower is a chain of inverters; driving the top and reading the
      bottom should propagate DOWN with per-torch inversion, same as up. Test it.
  DB: dust "see-below" straight down a 1-wide column — dust on stacked blocks
      where each dust reads the dust one level up-and-in the SAME (x,z)? Redstone
      dust travels down a 1-wide staircase only if each step is offset by 1 in a
      horizontal dir; a pure vertical 1x1 dust drop is NOT a thing. So DA is the
      real candidate.

For DA we need the TOP driven by a trunk dust. Model: trunk dust at (x, y_top, z)
sits on a block (x, y_top-1, z). That block, when powered by the dust... a block
under a powered dust becomes weakly powered — enough to turn an adjacent torch
OFF. So build the tower so its top torch reads the trunk-support block.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def rep_w(): return "minecraft:repeater[facing=west,delay=1]"
def wt(f): return f"minecraft:redstone_wall_torch[facing={f}]"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def DA_tower_down(drive, n_torches, base_y=0):
    """Drive the TOP of a torch tower, read the bottom dust. Tower at (x,z).
    We feed the top block from a trunk dust to its west (repeater), then the
    tower's torches carry the signal down. Read y0 dust below the tower base.

    Geometry (top-driven):
      trunk dust at (x, y_top, z) on support (x, y_top-1, z)   [top block]
      standing torch UNDER... torches can't hang. Use wall torches reading the
      column: at each level a wall torch on face reads the block, powers block
      below. Build a WALL-torch ladder in 1x2 (col x for blocks, x+1 for torches).
    Actually a *standing* torch sits on top of a block and powers the block ABOVE.
    For DOWN we want each level's state to set the level BELOW => wall torches.

    wall torch at (x+1, y, z) facing east reads block (x, y, z): torch ON when
    block UNpowered; torch powers the block it sits on's neighbors incl below-ish.
    A wall torch powers the block ABOVE its attachment and provides power to
    adjacent dust. Standard vertical DOWN transmission = torch ladder where each
    torch powers the block below the next torch. This is a 2-wide (x, x+1) ladder.

    Test both a 1-wide attempt (DA1, likely fails) and the 2-wide ladder (DA2).
    """
    sc = nuc.Schematic.create(f"da_{drive}_{n_torches}"); B = sc.set_block_from_string
    flr(B, -6, 8, -2, 6)
    x, z = 2, 1
    y_top = base_y + 2 * n_torches
    # drive the TOP: redstone_block/air -> wire -> repeater(west) -> top block
    B(x - 3, y_top, z, RB if drive else "minecraft:air")
    # need support for that block & wire path at y_top; put a pillar
    for yy in range(base_y, y_top):
        B(x - 3, yy - 0, z, S) if False else None
    # simpler: build a solid wall at x-3..x-1 up to y_top so the drive path floats on blocks
    for xx in (x - 3, x - 2, x - 1):
        for yy in range(base_y, y_top):
            B(xx, yy - 1, z, S)  # support columns (below the y_top path)
    B(x - 3, y_top, z, RB if drive else "minecraft:air")
    B(x - 2, y_top, z, W)
    B(x - 1, y_top, z, rep_w())            # drives east into top block
    B(x, y_top, z, S)                      # TOP block (strongly powered when drive=1)
    # torch ladder DOWN: wall torch on x+1 reading block at x, block below at x
    probes = []
    y = y_top
    for _ in range(n_torches):
        B(x + 1, y, z, wt("east"))         # wall torch reads block (x,y,z)
        B(x, y - 1, z, S)                  # block below (powered by torch? torch powers block it's ON)
        probes.append((x + 1, y, z))
        y -= 1
    # bottom dust
    B(x, base_y, z, W)
    B(x, base_y, z - 1, LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(40)
    seq = [1 if w.is_lit(*p) else 0 for p in probes]
    p0 = w.get_redstone_power(x, base_y, z)
    return seq, p0


def DC_repeater_down_pillar(drive, levels, base_y=0):
    """Alternative: a compact DOWN using repeaters is impossible (repeaters are
    horizontal). But we can do the SOURCE rise as a tower and avoid sink-drop
    entirely by putting the TRUNK BELOW the pins?? No, pins are at y0 floor.

    Instead: verify the cleanest known 1x2 DOWN — 'glowstone/observer' free.
    Skip; DA is the candidate. Placeholder."""
    return None


if __name__ == "__main__":
    print("=== DA: torch-ladder DOWN (drive top, read bottom) — footprint 1x2 (x,x+1) ===")
    for n in (2, 3, 4):
        for d in (0, 1):
            seq, p0 = DA_tower_down(d, n)
            print(f"  n={n} drive={d}: torch_seq(top..bot)={seq} bottom_y0_power={p0}")
        print()
