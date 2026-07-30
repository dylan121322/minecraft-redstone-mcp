"""diag_emit_gap.py — compare what the ROUTER thinks it placed for a net against
what actually reached the emitted block set. A net reported as routed but whose
wires are missing from the geometry means router->emit lost it (e.g. BuildResult
fields the emitter ignores, or bridge placements dropped)."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from build_from_route import emit_blocks


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n6"
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=4)
    print(f"failed={res.failed}")
    print(f"{net} in failed? {net in res.failed}")
    wires = res.wires.get(net, set())
    reps = res.repeaters.get(net, [])
    print(f"router says: {len(wires)} wires, {len(reps)} repeaters, "
          f"bridges={res.bridges.get(net)}")
    ys = sorted({p[1] for p in wires})
    print(f"  wire Y levels: {ys}")
    print(f"  first 8 wires: {sorted(wires)[:8]}")
    print(f"  repeaters: {reps[:4]}")
    print(f"  torches (global): {len(res.torches)}")
    # emit and check presence
    blocks = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 0 for n in nls["alu1"]["inputs"]})
    missing = [p for p in wires if p not in blocks]
    print(f"  wires missing from emitted blocks: {len(missing)} "
          f"{sorted(missing)[:6]}")
    src = pl.net_sources[net]; sinks = pl.net_sinks[net]
    print(f"  source={src} sinks={sinks}")
    # is there ANY wire of this net near each sink?
    for k in sinks:
        near = [p for p in wires if abs(p[0]-k[0]) <= 3 and abs(p[2]-k[2]) <= 3]
        print(f"  wires within 3 of sink {k}: {len(near)} {sorted(near)[:4]}")


if __name__ == "__main__":
    main()
