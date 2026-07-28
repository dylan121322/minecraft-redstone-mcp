"""
test_rise_final.py — DEFINITIVE, interface-fixed source RISE via.

Contract (matches emit_full's real usage):
  INPUT : a y0 redstone_wire (the gate's output pin dust) arriving from the WEST
          at (wx-1, base_y, wz).
  OUTPUT: a redstone_wire at (wx, y_hi, wz) on the trunk plane, carrying the SAME
          logic value (NON-inverting), for ANY trunk world-y = base_y+2*layer,
          layer >= 1, even OR odd.
  FOOTPRINT: 1x1 column at (wx,wz) for the tower; may use (wx, y_hi) trunk cell
             and at most a wall-torch on one side for odd-parity correction.

Mechanism:
  base:  y0 dust (wx-1) -> block0 (wx, base_y). A dust powers an adjacent solid
         block only WEAKLY (power 0 to the block's own emission) — NOT enough to
         flip a torch reliably. So we prime with a repeater: the caller guarantees
         the feed is a repeater OR we insert one. Here the incoming dust drives a
         repeater at (wx-1) facing... but the pin dust is fixed. TEST both:
           (a) dust directly adjacent to block0
           (b) dust -> repeater(facing=west) -> block0
  climb: n=layer torches, each {torch on top; block on top}, +2 Y each.
  parity: if n odd, the top is inverted; add a wall torch at the top to re-invert.
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


def emit_rise(B, wx, wz, base_y, layer, feed="repeater"):
    """Emit a non-inverting rise to trunk y=base_y+2*layer. Returns top dust y.
    feed: 'repeater' inserts RB/dust->repeater->block0 (caller drives the west
    dust). 'dust' relies on direct dust->block0 (weak, tested to compare)."""
    y_hi = base_y + 2 * layer
    n = layer                                   # torches (each +2 Y, inverts once)
    # base drive
    if feed == "repeater":
        B(wx - 1, base_y, wz, rep_w())          # repeater faces west, drives east
    B(wx, base_y, wz, S)                         # block0
    y = base_y
    for _ in range(n):
        B(wx, y + 1, wz, TORCH)
        B(wx, y + 2, wz, S)
        y += 2
    # now top BLOCK at y = y_hi; its state = drive XOR (n odd)
    if n % 2 == 1:
        # re-invert with a wall torch on the top block's side, output dust beside
        B(wx + 1, y_hi, wz, wt("west"))          # reads top block (wx,y_hi); output on wx+1
        B(wx + 1, y_hi, wz - 0, wt("west"))
        # the wall torch powers its own block cell region; read dust next to it
        out = (wx + 1, y_hi, wz)
        # place a support+dust so the trunk starts at (wx+1, y_hi)
        B(wx + 2, y_hi - 1, wz, S); B(wx + 2, y_hi, wz, W)
        return (wx + 2, y_hi, wz)
    else:
        B(wx, y_hi + 1, wz, W)                   # dust on top block (non-inverting)
        return (wx, y_hi + 1, wz)


def test(layer, drive, feed):
    sc = nuc.Schematic.create(f"r{layer}_{drive}_{feed}"); B = sc.set_block_from_string
    flr(B, -8, 8, -2, 4)
    wx, wz, base_y = 2, 1, 0
    # source: RB/air -> dust arriving from west at (wx-1) [repeater feed] or (wx-1) dust
    if feed == "repeater":
        B(wx - 3, base_y, wz, RB if drive else "minecraft:air")
        B(wx - 2, base_y, wz, W)
        # repeater is placed by emit_rise at (wx-1)
    else:
        B(wx - 2, base_y, wz, RB if drive else "minecraft:air")
        B(wx - 1, base_y, wz, W)
    top = emit_rise(B, wx, wz, base_y, layer, feed=feed)
    B(top[0] + 1, top[1], top[2], LAMP)
    w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(60)
    return w.get_redstone_power(*top)


if __name__ == "__main__":
    for feed in ("repeater", "dust"):
        print(f"\n=== feed={feed}: non-inverting rise to any layer ===")
        allok = True
        for layer in range(1, 9):
            p1 = test(layer, 1, feed)
            p0 = test(layer, 0, feed)
            ok = (p1 > 0 and p0 == 0)
            allok &= ok
            print(f"  layer={layer} ({'odd' if layer%2 else 'even'}): "
                  f"drive1->{p1} drive0->{p0}  {'OK' if ok else 'FAIL'}")
        print(f"  => {'ALL OK' if allok else 'SOME FAIL'}")
