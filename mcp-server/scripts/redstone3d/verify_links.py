"""
verify_links.py — plan C: validate that the ROUTED nets actually carry a signal
end-to-end in the real emitted geometry, without needing the whole chip to be
routed (3 nets are still unrouted, which would leave downstream gates floating
and force every primary output stuck-high, masking everything).

Method: build the emitted block set in MCHPRS once per test, force the chosen
net's SOURCE to 1/0 at the driver pin, and read each SINK's west feed cell (the
cell a gate-input repeater reads). A correct net gives sink=source (the whole
rise/tower/cross/descent chain is non-inverting), and sink=0 when source=0
(no stuck-high).
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
import nucleation as nuc

RB = "minecraft:redstone_block"
W = "minecraft:redstone_wire"


def test_net(blocks, net, src, sinks, base_y):
    """Drive the net's source pin, read each sink's west feed."""
    out = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"lk_{net}_{drive}")
        for (x, y, z, s) in blocks:
            sc.set_block_from_string(x, y, z, s)
        sx, sz = src[0], src[2]
        # Force the driver: a redstone_block WEST of the source pin drives the
        # source dust/pin. The source pin itself stays whatever the cell emitted.
        sc.set_block_from_string(sx - 1, base_y, sz,
                                 RB if drive else "minecraft:air")
        sc.set_block_from_string(sx, base_y, sz, W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(60)
        reads = []
        for k in sinks:
            kx, kz = k[0], k[2]
            reads.append(w.get_redstone_power(kx - 1, base_y, kz))
        out[drive] = reads
    return out


def main():
    d = json.load(open("/tmp/alu1_buildable.json"))
    blocks = d["blocks"]; base_y = d["base_y"]
    routed = d["routed"]; srcs = d["net_sources"]; snks = d["net_sinks"]
    which = sys.argv[1:] if len(sys.argv) > 1 else routed[:6]
    print(f"testing {len(which)} routed nets (of {len(routed)} routed, "
          f"failed={d['failed']})", flush=True)
    ok = 0
    for net in which:
        if net not in srcs:
            print(f"  {net}: no source, skip", flush=True); continue
        r = test_net(blocks, net, srcs[net], snks[net], base_y)
        lo, hi = r[0], r[1]
        good = all(v == 0 for v in lo) and all(v > 0 for v in hi)
        ok += good
        print(f"  {net}: drive0->{lo}  drive1->{hi}  "
              f"{'OK' if good else 'BAD'}", flush=True)
    print(f"links OK: {ok}/{len(which)}")


if __name__ == "__main__":
    main()
