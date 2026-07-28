"""
test_down_compact.py — find the MINIMAL-footprint reliable DOWN via (trunk high
-> y0 sink). 1x1 torch tower down is physically impossible (torches only power
upward). We need the tightest dust/torch DOWN that still conducts N levels.

Candidates (MCHPRS):
  E1: dust see-below staircase folded into 2 columns (x, x+1) — descend 1 level
      per step but zig-zag between x and x+1 so it stays 2-wide regardless of
      depth (vs the +x staircase that grows with depth).
  E2: wall-torch ladder DOWN in 2 columns done RIGHT — each level: block at x,
      wall torch at x+1 reading it, the torch powers the block BELOW-adjacent so
      the signal steps down. Need the torch to power the next-lower block.
  E3: dust spiral in a 2x2 shaft — 4 cells, descend 1 level per quarter-turn,
      constant 2x2 footprint any depth.

Goal metric: a DOWN via whose PLAN footprint does NOT grow with depth (so deep
trunks don't create wide short surfaces). 2x1 or 2x2 constant is acceptable;
+x-linear (old drop_cells) is NOT.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
TORCH = "minecraft:redstone_torch"; LAMP = "minecraft:redstone_lamp"
def rep_w(): return "minecraft:repeater[facing=west,delay=1]"

def flr(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def E1_zigzag_2col(drive, levels, base_y=0):
    """Dust see-below descent zig-zagging between x and x+1, constant 2-wide.
    Top dust at (x, y_top). Each level down alternates column x<->x+1 so the
    footprint stays {x, x+1} for any depth.
      level k (y = y_top-k): dust at col = x if k even else x+1, on a support
      block one below; the previous dust (one higher, other col) is diagonally
      adjacent above => see-below conducts down."""
    sc = nuc.Schematic.create(f"e1_{drive}_{levels}"); B = sc.set_block_from_string
    y_top = base_y + levels
    flr(B, -6, 6, -2, 4)
    x, z = 2, 1
    # drive top dust at (x, y_top, z) from a west repeater on a pillar
    for yy in range(base_y, y_top):
        B(x - 3, yy - 1, z, S); B(x - 2, yy - 1, z, S); B(x - 1, yy - 1, z, S)
    B(x - 3, y_top, z, RB if drive else "minecraft:air")
    B(x - 2, y_top, z, W)
    B(x - 1, y_top, z, rep_w())
    B(x, y_top, z, S)          # block the repeater drives (top of descent feed)
    B(x, y_top + 1, z, W)      # actually feed a dust ON TOP so descent can begin
    # Hmm: simpler — top dust sits at (x, y_top, z) fed by repeater to a block at
    # (x-1..) — but repeater must be at dust level. Redo: put top dust at y_top,
    # supported, fed by repeater at same y.
    sc = nuc.Schematic.create(f"e1b_{drive}_{levels}"); B = sc.set_block_from_string
    flr(B, -6, 8, -2, 4)
    # build a support pillar so the repeater feed sits at y_top
    for yy in range(base_y, y_top + 1):
        for xx in (x - 3, x - 2, x - 1):
            B(xx, yy - 1, z, S)
    B(x - 3, y_top, z, RB if drive else "minecraft:air")
    B(x - 2, y_top, z, W)
    B(x - 1, y_top, z, rep_w())      # drives east into (x, y_top) — but that must be a block
    B(x, y_top, z, S)                # feed block
    B(x, y_top, z + 0, S)
    # descent dust starts on top of feed block, then zig-zags down
    col = [x, x + 1]
    probes = []
    cy = y_top
    # first descent dust on top of feed block
    B(x, y_top + 1, z, W); top_dust = (x, y_top + 1, z)
    # Now zig-zag DOWN from y_top+1 to base_y
    prev = (x, y_top + 1)
    k = 0
    cy = y_top + 1
    while cy > base_y:
        cy -= 1
        cx = col[k % 2]
        if cy > base_y:
            B(cx, cy - 1, z, S)
        B(cx, cy, z, W)
        probes.append((cx, cy, z))
        k += 1
    B(probes[-1][0], base_y, z - 1, LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(50)
    botp = w.get_redstone_power(*probes[-1])
    return botp, top_dust


def E2_walltorch_down(drive, levels, base_y=0):
    """Wall-torch ladder DOWN, 2-wide. block column at x; at each level a wall
    torch on x+1 (facing east, reads block x). The torch, being ON when block
    unpowered, powers the block it's placed against and the block below? A wall
    torch provides power to the block ABOVE it and adjacent. To step DOWN we want
    torch at level y to set block at y-1. Test: does wall torch power block below?"""
    sc = nuc.Schematic.create(f"e2_{drive}_{levels}"); B = sc.set_block_from_string
    y_top = base_y + levels
    flr(B, -6, 8, -2, 4)
    x, z = 2, 1
    for yy in range(base_y, y_top + 1):
        for xx in (x - 3, x - 2, x - 1):
            B(xx, yy - 1, z, S)
    B(x - 3, y_top, z, RB if drive else "minecraft:air")
    B(x - 2, y_top, z, W)
    B(x - 1, y_top, z, rep_w())
    B(x, y_top, z, S)               # top block powered
    probes = []
    y = y_top
    while y > base_y:
        B(x, y - 1, z, S)           # block below
        B(x + 1, y - 1, z, f"minecraft:redstone_wall_torch[facing=east]")  # torch reads block(x,y-1)?
        probes.append((x + 1, y - 1, z))
        y -= 1
    B(x, base_y, z, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(50)
    seq = [1 if w.is_lit(*p) else 0 for p in probes]
    botp = w.get_redstone_power(x, base_y, z)
    return seq, botp


if __name__ == "__main__":
    print("=== E1: dust zig-zag DOWN, constant 2-wide {x,x+1} ===")
    for lv in (4, 8, 16, 26):
        r0, _ = E1_zigzag_2col(0, lv)
        r1, _ = E1_zigzag_2col(1, lv)
        ok = (r0 == 0 and r1 > 0)
        print(f"  levels={lv:2d}: drive0->bot={r0} drive1->bot={r1}  {'OK' if ok else 'FAIL'}")
    print("\n=== E2: wall-torch ladder DOWN ===")
    for lv in (4, 8):
        seq1, p1 = E2_walltorch_down(1, lv)
        seq0, p0 = E2_walltorch_down(0, lv)
        print(f"  levels={lv}: drive1 bot={p1} seq={seq1[:6]}.. | drive0 bot={p0}")
