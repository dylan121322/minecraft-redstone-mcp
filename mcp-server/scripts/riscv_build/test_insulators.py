"""
test_insulators.py — the router has only ever used dust / repeater / torch /
stone. Two untried levers:

  A. NON-CONDUCTIVE support blocks. A powered dust strongly powers the solid
     block under it, and that block then powers anything adjacent — which is the
     see-below / ramp coupling that forces wide keep-outs. If the support is a
     block that CANNOT be powered (glass, and other transparent/"non-solid"
     blocks that still hold dust), the coupling path disappears and two nets can
     run one cell apart.

  B. Other components: comparators, observers, target blocks, trapdoors, slabs.
     A comparator in subtract mode or a target block can also isolate/steer.

This measures, for each candidate block:
  1. can dust be placed ON it (does it support a wire)?
  2. does a powered dust ABOVE it energise a dust BESIDE it (the coupling we
     want to kill)?
  3. does a wire ON it still conduct along the line (must stay yes)?
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
STONE = "minecraft:stone"

CANDIDATES = [
    "minecraft:stone",              # baseline, conductive
    "minecraft:glass",
    "minecraft:white_stained_glass",
    "minecraft:obsidian",
    "minecraft:iron_block",
    "minecraft:slime_block",
    "minecraft:honey_block",
    "minecraft:target",
    "minecraft:smooth_stone_slab",
    "minecraft:oak_trapdoor",
    "minecraft:glowstone",
    "minecraft:sea_lantern",
    "minecraft:packed_ice",
    "minecraft:soul_sand",
    "minecraft:cut_copper",
]


def floor(B, y=-2, r=10):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, STONE)


def test_block(blk):
    """Three probes on one candidate support block.

    layout (y=0 is the wire plane, y=-1 the support under it):
        (-3,0,0) RB driver -> (-2,0,0) wire -> (-1,0,0) wire -> (0,0,0) wire
        supports at y=-1 under each of those, made of `blk` at x=0 only
        victim dust at (0,-1,1): one level DOWN and one across from (0,0,0)
        continuation at (1,0,0): must still light if the wire conducts
    """
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"ins_{abs(hash(blk))%9999}_{drive}")
        B = sc.set_block_from_string
        floor(B)
        # driver + line, supports of plain stone except the cell under test
        B(-3, 0, 0, RB if drive else "minecraft:air")
        for x in (-3, -2, -1):
            B(x, -1, 0, STONE)
        for x in (-2, -1):
            B(x, 0, 0, W)
        B(0, -1, 0, blk)          # the support UNDER the wire being tested
        B(0, 0, 0, W)             # wire on the candidate block
        B(1, -1, 0, STONE)
        B(1, 0, 0, W)             # continuation: proves the line still conducts
        # victim one level down, one cell across (see-below coupling)
        B(0, -2, 1, STONE)
        B(0, -1, 1, W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(25)
        out[drive] = {
            "on_block": w.get_redstone_power(0, 0, 0),
            "continues": w.get_redstone_power(1, 0, 0),
            "victim": w.get_redstone_power(0, -1, 1),
        }
    return out


if __name__ == "__main__":
    print(f"{'block':32s} {'holds/conducts':>14s} {'see-below leak':>15s}  verdict")
    print("-" * 92)
    for blk in CANDIDATES:
        try:
            r = test_block(blk)
        except Exception as e:
            print(f"{blk:32s} ERROR {type(e).__name__}: {str(e)[:40]}")
            continue
        conducts = r[1]["continues"] > 0 and r[1]["on_block"] > 0
        leaks = r[1]["victim"] != r[0]["victim"]
        if conducts and not leaks:
            verdict = "INSULATOR — wire works, no leak"
        elif conducts and leaks:
            verdict = "conductive (leaks like stone)"
        elif not conducts:
            verdict = "does NOT carry the wire"
        print(f"{blk:32s} {str(r[1]['on_block'])+'/'+str(r[1]['continues']):>14s} "
              f"{str(r[0]['victim'])+'->'+str(r[1]['victim']):>15s}  {verdict}")
