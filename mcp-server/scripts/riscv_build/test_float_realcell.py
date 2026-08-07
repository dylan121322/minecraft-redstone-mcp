"""
test_float_realcell.py — what does a REAL library gate output when its input net
is routed-but-broken (a wire that goes nowhere) vs truly floating?

The y-stuck hypothesis: a gate whose input is unrouted sees a floating pin and
its output torch defaults ON. But test_not_target_chain showed a NOT whose input
repeater sees air outputs 1 — which is CORRECT (air=0, NOT=1). So the question
is subtler: in a real failed route, does the input pin see 0 (broken wire, dust
with no source => 0) or does it float to 1?

Test with the REAL NAND/OR cell from the library:
  - input pin driven by a dust that has NO source (broken route): pin reads 0?
  - input pin with NOTHING at all (air): pin reads 0?
  - the gate output in both cases.
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc
import cell_library as clib

S = "minecraft:stone"; W = "minecraft:redstone_wire"
RB = "minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"


def floor(B, y=-1, r=12):
    for x in range(-r, r + 1):
        for z in range(-r, r + 1):
            B(x, y, z, S)


def build(gtype, mode, drive):
    """mode: 'broken' = input dust with no source; 'air' = nothing;
    'drive' = driven."""
    sc = nuc.Schematic.create(f"fr_{gtype}_{mode}_{drive}")
    B = sc.set_block_from_string
    floor(B)
    cell = clib.get(gtype)
    A = cell.inputs["A"]
    az = A[2]
    if mode == "drive":
        B(-3, 0, az, RB if drive else "minecraft:air")
        B(-2, 0, az, W); B(-1, 0, az, W)
    elif mode == "broken":
        # a wire that goes nowhere: dust at the feed but no source beyond
        B(-2, 0, az, W); B(-1, 0, az, W)
    # mode == 'air': nothing at all
    cell.emit(sc, 0, 0, 0)
    q = cell.outputs["Q"]
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(50)
    pin = w.get_redstone_power(-1, 0, az)      # the west feed cell
    out = w.get_redstone_power(q[0], q[1], q[2])
    return pin, out


if __name__ == "__main__":
    for gtype in ("NAND", "OR"):
        print(f"\n{gtype}:")
        for mode in ("drive", "broken", "air"):
            for dv in (0, 1):
                pin, out = build(gtype, mode, dv)
                print(f"  {mode:6s} drive={dv}: pin_feed={pin} gate_out={out}")
