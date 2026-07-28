"""
Verify the CAP=3-reuse + horizontal-via scheme's core assumption:
multiple nets sharing a shallow trunk layer, each reaching it via a horizontal
rise within the routing channel, don't collide — and each carries signal.

Scene: 2 nets on trunk layer 2 (y=4), sources at different z on the west edge,
each rises horizontally into the channel, runs on the trunk, drops to a NOT pin.
If both NOTs invert correctly AND no short => the scheme works; then worth the
route rewrite.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nucleation as nuc
from via_gadget import rise_cells, drop_cells
W="minecraft:redstone_wire"; S="minecraft:stone"; RB="minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"

def build(d0, d1):
    sc = nuc.Schematic.create("sv"); B = sc.set_block_from_string
    for x in range(-3, 60):
        for z in range(-3, 8): B(x, -1, z, S)
    trunk_y = 4
    outs = {}
    # two nets at z=0 and z=4 (spaced), both rise to trunk_y, run, drop to NOT
    for k, (z, drive) in enumerate([(0, d0), (4, d1)]):
        B(-1, 0, z, RB if drive else "minecraft:air")
        B(0, 0, z, W)
        pr, xo = rise_cells(0, z, 0, trunk_y)
        for (x, y, zz, b) in pr: B(x, y, zz, b)
        # rise top dust is at (xo, trunk_y). Repeater refresh goes at xo+1
        # (reads rise-top from west, drives east). Then trunk dust from xo+2.
        B(xo, trunk_y-1, z, S)                                    # support under rise-top dust
        B(xo+1, trunk_y-1, z, S); B(xo+1, trunk_y, z, rep("west"))  # refresh at xo+1
        for x in range(xo+2, xo+10): B(x, trunk_y-1, z, S); B(x, trunk_y, z, W)
        tx = xo+9
        pd, xo2 = drop_cells(tx, z, trunk_y, 0)
        for (x, y, zz, b) in pd: B(x, y, zz, b)
        # NOT pin at xo2+2
        B(xo2+1, 0, z, W); B(xo2+2, 0, z, rep("west"))
        B(xo2+3, 0, z, S); B(xo2+4, 0, z, "minecraft:redstone_wall_torch[facing=east]")
        B(xo2+5, 0, z, W)
        outs[k] = (xo2+5, 0, z)
    return sc, outs

# short check + logic
def shorts(sc):
    # crude: build world, count nothing here; rely on logic correctness (a short
    # would corrupt one net's output when the other toggles)
    return 0

ok = True
for d0 in (0, 1):
    for d1 in (0, 1):
        sc, outs = build(d0, d1)
        w = nuc.MchprsWorld.create_with_options(sc, True, False); w.tick(80)
        o0 = 1 if w.get_redstone_power(*outs[0]) > 0 else 0
        o1 = 1 if w.get_redstone_power(*outs[1]) > 0 else 0
        e0, e1 = 1-d0, 1-d1   # each is a NOT of its drive
        good = (o0 == e0 and o1 == e1)
        ok = ok and good
        print(f"  d0={d0} d1={d1}: NOT0={o0}(e{e0}) NOT1={o1}(e{e1}) {'OK' if good else 'X'}")
print("shallow-via 2-net:", "PASS" if ok else "FAIL")
