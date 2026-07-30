"""diag_link.py — why does a routed net read 0 at its sinks? Inspect the real
geometry around the source and probe the signal at successive points along the
net (source pin, its first routed dust, the tower base if any, the cross plane,
the descent landing, the sink feed)."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
import nucleation as nuc

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def main():
    d = json.load(open("/tmp/alu1_buildable.json"))
    blocks = d["blocks"]; base_y = d["base_y"]
    bm = {(x, y, z): s for (x, y, z, s) in blocks}
    net = sys.argv[1] if len(sys.argv) > 1 else "n6"
    src = d["net_sources"][net]; sinks = d["net_sinks"][net]
    sx, sy, sz = src
    print(f"{net} source={src} sinks={sinks} base_y={base_y}")
    print("--- geometry around source (y0), x=sx-3..sx+6 ---")
    for x in range(sx - 3, sx + 7):
        print(f"  ({x},{base_y},{sz}): {bm.get((x, base_y, sz), '<empty>')}")
    print("--- what is at the sink feeds ---")
    for k in sinks:
        kx, kz = k[0], k[2]
        for x in range(kx - 3, kx + 2):
            print(f"  sink({kx},{kz}) x={x}: {bm.get((x, base_y, kz), '<empty>')}")
    # build once, drive the PI injection point if this net is a PI, else the pin
    pis = d["primary_inputs"]
    sc = nuc.Schematic.create("dl")
    for (x, y, z, s) in blocks:
        sc.set_block_from_string(x, y, z, s)
    if net in pis:
        p = pis[net]
        sc.set_block_from_string(p[0] - 1, p[1], p[2], RB)
        print(f"driving PI {net} at {p} (block at x-1)")
    else:
        sc.set_block_from_string(sx - 1, base_y, sz, RB)
        print(f"driving internal source at {src} (block at x-1)")
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(60)
    print("--- probes ---")
    print(f"  source pin ({sx},{base_y},{sz}) pow={w.get_redstone_power(sx, base_y, sz)}")
    for dx in (1, 2, 3, 4, 5):
        q = (sx + dx, base_y, sz)
        if q in bm:
            print(f"  y0 +{dx} {q} [{bm[q].split(':')[1][:22]}] pow={w.get_redstone_power(*q)}")
    # scan upward at source column for a tower
    for y in range(base_y, base_y + 30):
        q = (sx + 1, y, sz)
        if q in bm:
            print(f"  tower col ({sx+1},{y},{sz}) [{bm[q].split(':')[1][:20]}] "
                  f"pow={w.get_redstone_power(*q)}")
    for k in sinks:
        kx, kz = k[0], k[2]
        print(f"  sink pin ({kx},{base_y},{kz}) pow={w.get_redstone_power(kx, base_y, kz)} "
              f"feed({kx-1}) pow={w.get_redstone_power(kx-1, base_y, kz)}")


if __name__ == "__main__":
    main()
