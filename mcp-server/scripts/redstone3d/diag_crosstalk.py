"""diag_crosstalk.py — a sink that reads the SAME value whatever we drive is
being fed by something else. The rep-aware short check reports 0, so the coupling
must be a class it does not model (vertical dust<->block, a cross-plane dust
sitting above a y0 wire, a torch powering a neighbouring block, ...). Find the
real driver: cut the net's own feed, then probe what still powers the sink cell
and dump every block within a small radius so the coupling path is visible."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n27"
    d = json.load(open("/tmp/alu1_buildable.json"))
    blocks = d["blocks"]; base_y = d["base_y"]
    bm = {(x, y, z): s for (x, y, z, s) in blocks}
    src = d["net_sources"][net]; sinks = d["net_sinks"][net]
    print(f"{net} source={src} sinks={sinks}")

    # build with the net's source CUT (air at the published source) so anything
    # still powering the sink is foreign
    sc = nuc.Schematic.create("ct")
    for (x, y, z), s in bm.items():
        sc.set_block_from_string(x, y, z, s)
    sc.set_block_from_string(src[0]-1, base_y, src[2], "minecraft:air")
    sc.set_block_from_string(src[0], base_y, src[2], "minecraft:air")
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(60)
    for k in sinks:
        kx, kz = k[0], k[2]
        feed = (kx-1, base_y, kz)
        p = w.get_redstone_power(*feed)
        print(f"  sink {k}: feed{feed} power WITH SOURCE CUT = {p}")
        if p == 0:
            continue
        print("   neighbourhood (dx,dy,dz -> block, power):")
        for dy in (2, 1, 0, -1):
            for dz in (-1, 0, 1):
                row = []
                for dx in (-2, -1, 0, 1, 2):
                    q = (feed[0]+dx, feed[1]+dy, feed[2]+dz)
                    s = bm.get(q)
                    if not s:
                        row.append(".")
                        continue
                    tag = ("W" if "wire" in s else
                           "R" if "repeater" in s else
                           "T" if "torch" in s else
                           "#" if s == "minecraft:stone" else
                           "B" if "redstone_block" in s else "?")
                    pw = w.get_redstone_power(*q)
                    row.append(f"{tag}{pw}" if pw else tag)
                print(f"     dy={dy:+d} dz={dz:+d}: {' '.join(f'{c:>3}' for c in row)}")


if __name__ == "__main__":
    main()
