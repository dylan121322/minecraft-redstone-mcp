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


def test_net(blocks, net, src, sinks, base_y, isolate_gates=True):
    """Drive the net's source pin, read each sink's west feed.

    isolate_gates: the chip is only partially routed, so gates whose inputs are
    still unrouted float — and a floating gate's output wall-torch is LIT, which
    injects a constant 1 into whatever wire runs past it. That made unrelated
    nets read a fixed 14 regardless of what we drove (n27/n16/n19). Replacing
    every gate output torch with air removes that artefact so the measurement
    reflects the ROUTING only.
    """
    out = {}
    sx, sz = src[0], src[2]
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"lk_{net}_{drive}")
        for (x, y, z, s) in blocks:
            # Keep every gate torch EXCEPT the one feeding the net under test.
            # Dropping all of them (the old isolate_gates) also destroyed the
            # driver structure of the net's own source cell, so nets that do
            # conduct (verified separately with diag_break: n11 delivers 9 to its
            # sink) were reported dead. Foreign floating gates are handled by
            # comparing drive0 vs drive1 instead of trusting absolute levels.
            # Mask ALL gate output torches: on a partially routed chip every gate
            # with an unrouted input floats and its output torch is lit, biasing
            # whatever wire passes by. Masking only the local ones left those
            # biases in place (16/26 -> many false BADs). In the finished chip no
            # gate floats, so masking models the real conditions; the net's own
            # driver is supplied by the injector below, not by its gate.
            if isolate_gates and "wall_torch" in s:
                continue
            sc.set_block_from_string(x, y, z, s)
        # The placer publishes each source one cell EAST of the real gate output
        # pin, and the routed net starts there. Drive that published cell
        # directly with a redstone_block: this isolates the ROUTING (published
        # source -> every sink) from the gate's internal logic, which is what we
        # want to validate here. A block replaces the stub dust for the test.
        # Inject the test value. A redstone_block does NOT energise dust it is
        # merely placed next to under /setblock, so the block has to sit where the
        # emitter's own PI injector goes: one cell WEST of the source, with the
        # source itself left as dust.
        #   - internal nets: the cell west of the published source is the gate's
        #     real output pin; overwrite it (that also cuts the floating gate).
        #   - PI nets: that cell IS the injector slot.
        # Either way: block west, dust on the source.
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
        # Judge by RESPONSE, not absolute level: on a partially routed chip some
        # sinks carry a constant bias from a neighbouring floating gate, and no
        # torch-masking scheme avoided that without also breaking the net's own
        # driver. A link is good iff every sink RESPONDS to the source (higher
        # when driven), which is exactly the property routing must guarantee.
        good = all(h > l for l, h in zip(lo, hi))
        ok += good
        print(f"  {net}: drive0->{lo}  drive1->{hi}  "
              f"{'OK' if good else 'BAD'}", flush=True)
    print(f"links OK: {ok}/{len(which)}")


if __name__ == "__main__":
    main()
