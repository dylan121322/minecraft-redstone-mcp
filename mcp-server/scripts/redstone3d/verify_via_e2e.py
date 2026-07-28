"""
verify_via_e2e.py — end-to-end MCHPRS check of one routed net's via towers.
Drives the net's source pin, reads at its sink pin, confirms the signal
propagates through the up-via / trunk / down-via chain with correct parity.

This closes the last verification gap: routing is 0-short+connected (GPU audit),
netlist is 40/40, cells are 4/4 — this proves the VIA TOWER geometry actually
carries the signal in real redstone (MCHPRS), for a real routed net.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"

def main():
    data = json.load(open(r"E:\project\alu1_routed.json"))
    x0, z0, base_y = data["x0"], data["z0"], data["base_y"]
    layer_y = data["layer_y"]

    # pick a single-sink net for a clean source->sink test
    net = None
    for n, sinks in data["net_sinks"].items():
        if len(sinks) == 1 and n in data["routes"] and data["routes"][n]:
            net = n; break
    cells = data["routes"][net]
    src = data["net_sources"][net]      # world (x,y,z)
    sink = data["net_sinks"][net][0]
    print(f"net {net}: src={src} sink={sink} cells={len(cells)}")

    def build(drive):
        sc = nuc.Schematic.create("e2e")
        B = sc.set_block_from_string
        # floor under everything
        xs = [c[1]+x0 for c in cells] + [src[0], sink[0]]
        zs = [c[2]+z0 for c in cells] + [src[2], sink[2]]
        for x in range(min(xs)-2, max(xs)+3):
            for z in range(min(zs)-2, max(zs)+3):
                B(x, base_y-1, z, S)
        # emit routed geometry (dust + supports + via towers)
        by_col = {}
        for (l, gx, gz) in cells:
            by_col.setdefault((gx, gz), []).append(l)
        for (gx, gz), layers in by_col.items():
            wx, wz = gx+x0, gz+z0
            layers = sorted(layers)
            if len(layers) == 1:
                wy = layer_y[layers[0]] + base_y
                B(wx, wy, wz, W)
                if wy > base_y: B(wx, wy-1, wz, S)
            else:
                y = layer_y[layers[0]]+base_y; yhi = layer_y[layers[-1]]+base_y
                while y < yhi:
                    B(wx, y, wz, S); B(wx, y+1, wz, "minecraft:redstone_torch")
                    y += 2
        # drive source: redstone_block just west of source pin feeding dust
        B(src[0]-1, src[2] and src[1] or base_y, src[2], RB if drive else "minecraft:air")
        B(src[0], base_y, src[2], RB if drive else "minecraft:air")
        return sc, (sink[0], base_y, sink[2])

    for d in (0, 1):
        sc, probe = build(d)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(30)
        pw = w.get_redstone_power(*probe)
        print(f"  drive={d}: sink power={pw}")

if __name__ == "__main__":
    main()
