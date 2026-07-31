"""
test_shell_conduction.py — is a STONE shell actually an isolator?

Module verification now shows sinks sitting at a constant 4-8 regardless of the
source: a constant driver is reaching them. The suspicion is the shell itself —
stone is not an insulator. A powered dust next to a stone block turns that block
into a powered block, and a powered block energises dust resting on it. If the
shell touches both an outside live wire and an inside dust cell, it conducts
straight through the "isolation".

The earlier hostile test put interference beside the shell but never arranged the
worst case: outside dust and inside dust sharing ONE shell block. That is what this
measures, plus the two candidate fixes.

Fixes under test:
  F1  double-thick shell (two stone layers) — the outside layer takes the charge,
      the inside layer stays neutral
  F2  air gap inside the shell (stone, then a one-cell void, then the interior)
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"


def run(shell_layers, air_gap, outside_live, ticks=30):
    """Interior dust at x=0; shell to its east; live dust beyond the shell."""
    sc = nuc.Schematic.create(f"sc_{shell_layers}_{air_gap}_{outside_live}")
    B = sc.set_block_from_string
    for x in range(-8, 20):
        for z in range(-4, 4):
            B(x, -1, z, S)
    # interior: an isolated dust cell, nothing driving it
    B(0, 0, 0, W)
    x = 1
    for _ in range(air_gap):
        x += 1                      # leave the cell empty (air)
    for _ in range(shell_layers):
        B(x, 0, 0, S)
        B(x, 1, 0, S)
        B(x, -1, 0, S)
        x += 1
    # outside: a live dust run pressed against the shell
    if outside_live:
        B(x, 0, 0, W)
        B(x + 1, 0, 0, RB)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return w.get_redstone_power(0, 0, 0)


if __name__ == "__main__":
    print("=== does a stone shell leak? (interior dust has NO driver of its own) ===")
    print("    any non-zero reading means the shell conducted the outside signal in")
    for layers in (1, 2, 3):
        for gap in (0, 1):
            live = run(layers, gap, True)
            dead = run(layers, gap, False)
            verdict = "LEAKS" if live > 0 else "isolates"
            print(f"  shell={layers} layer(s) air_gap={gap}: "
                  f"outside_live -> interior={live:2d} | outside_dead -> {dead:2d}"
                  f"   {verdict}")
