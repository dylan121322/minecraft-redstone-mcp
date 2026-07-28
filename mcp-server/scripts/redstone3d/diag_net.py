"""
diag_net.py — isolate ONE net's rise->trunk->drop in the full geometry and check
signal continuity. We take the full blocks, but instead of injecting PIs we force
the chosen net's SOURCE feed to 1/0 and read each SINK. This tells us whether the
emit'd rise/trunk/drop actually conducts a net end-to-end.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
from placer import place

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"; S = "minecraft:stone"

def main():
    full = json.load(open("/tmp/alu1_full.json"))
    even = json.load(open("/tmp/alu1_even.json"))
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    net = sys.argv[1] if len(sys.argv) > 1 else "n6"
    blocks = {(x, y, z): s for x, y, z, s in full["blocks"]}
    base_y = even["base_y"]

    src = pl.net_sources.get(net)
    sinks = pl.net_sinks.get(net, [])
    print(f"net {net}: source={src} sinks={sinks}")

    # The source pin (swx,swz) at y0 is where the tower's repeater reads from its
    # west (swx-1). Force that west feed to drive/0. Read each sink's y0 dust
    # (which feeds the pin at kwx-1..kwx).
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"diag_{net}_{drive}")
        for (x, y, z), s in blocks.items():
            sc.set_block_from_string(x, y, z, s)
        # force source: put RB/air at the repeater's west feed (swx-1 is repeater;
        # its input is swx-2). Actually emit places repeater at swx-1 facing west,
        # reading swx-2. Drive swx-2.
        swx, swz = src[0], src[2]
        sc.set_block_from_string(swx - 2, base_y, swz, RB if drive else "minecraft:air")
        # ensure a dust at swx-2 exists so the repeater reads it — emit may not
        # have placed one for a PI-less net. Add a wire west of it too.
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(60)
        # read trunk top at source column and each sink drop landing
        from collections import Counter
        cells = even["routes"][net]
        lc = Counter(l for l, gx, gz in cells); trunk = lc.most_common(1)[0][0]
        trunk_wy = base_y + 2 * trunk + 1
        tp = w.get_redstone_power(swx, trunk_wy, swz)
        sink_reads = []
        for k in sinks:
            kwx, kwz = k[0], k[2]
            # sink pin feed is at kwx-1 (west of the input repeater)
            sink_reads.append(w.get_redstone_power(kwx - 1, base_y, kwz))
        print(f"  drive={drive}: trunk_top@src={tp}  sink_feeds={sink_reads}")

if __name__ == "__main__":
    main()
