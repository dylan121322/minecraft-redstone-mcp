"""
export_solution.py — convert a pathfinder3d placements solution (e.g.
alu1_solution_40of40.json) into the bot build JSON consumed by
riscv_build/build_verify.cjs:

    {name, kind, blocks:[[x,y,z,state]...], inputs:{net:[ix,iy,iz]},
     outputs:{net:[x,y,z]}, input_bits, output_bits, gates}

Same emitter as the MCHPRS validation (emit_blocks), so the in-game build is
EXACTLY the verified circuit. All-zero input vector at export: the PI inject
cells are left for the bot to drive per test vector (build_verify skips them).

usage: python3 export_solution.py [placements.json] [out.json]
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "riscv_synth"))
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks

NETLISTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "riscv_synth", "netlists.json")


def _load_netlists():
    return json.load(open(NETLISTS))


def main():
    fname = sys.argv[1] if len(sys.argv) > 1 else "alu1_solution_40of40.json"
    out = sys.argv[2] if len(sys.argv) > 2 else "alu1_build.blocks.json"
    dump = json.load(open(fname))
    placements = dump["placements"]
    mod = dump.get("mod", "alu1")
    nls = _load_netlists()
    nl = nls[mod]
    pl = place(nl, col_gap=dump.get("col_gap", 16), row_gap=16)

    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})

    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    zero = {k: 0 for k in nl["inputs"]}
    emit_blocks(setter, pl, res, zero)

    # PI injection cells: the bot drives these per vector (redstone_block=1,
    # air=0). Drop them from the static block list.
    inj = {net: [pos[0] - 1, pos[1], pos[2]]
           for net, pos in pl.primary_inputs.items()}
    inj_set = {tuple(p) for p in inj.values()}
    blocks = [[x, y, z, s] for (x, y, z), s in rec.items()
              if (x, y, z) not in inj_set]

    outs = {net: list(pos) for net, pos in pl.primary_outputs.items()}

    # SUPPORT AUDIT: every dust/repeater cell must sit on a solid block —
    # MCHPRS tolerates floating wires but the real game pops them (measured:
    # a y2 lane node above a riser interior dropped as an item in-game).
    need_support = {"minecraft:redstone_wire"} | {
        f"minecraft:repeater[facing={f},delay=1]"
        for f in ("west", "east", "north", "south")}
    solid = {"minecraft:stone", "minecraft:glass", "minecraft:target"}
    blk = {(x, y, z): s for (x, y, z), s in rec.items()}
    floaters = []
    for (x, y, z), s in rec.items():
        if s in need_support and blk.get((x, y - 1, z)) not in solid:
            floaters.append((x, y, z, s, blk.get((x, y - 1, z))))
    if floaters:
        for f in floaters[:10]:
            print(f"  FLOATING: {f}")
        raise SystemExit(f"ABORT: {len(floaters)} floating dust/repeater cells "
                         f"— in-game these pop off")

    data = {
        "name": mod,
        "kind": "module",
        "blocks": blocks,
        "inputs": inj,
        "outputs": outs,
        "input_bits": list(nl["inputs"]),
        "output_bits": list(nl["outputs"]),
        "gates": len(nl["cells"]),
        # probe points: each net's sink feed cells (west of the input pins)
        # for in-game power diagnostics
        "feeds": {net: [[k[0] - 1, k[1], k[2]] for k in pl.net_sinks[net]]
                  for net in sorted(pl.net_sinks)},
    }
    with open(out, "w") as f:
        json.dump(data, f)
    xs = [b[0] for b in blocks]; ys = [b[1] for b in blocks]
    zs = [b[2] for b in blocks]
    print(f"exported {mod}: {len(blocks)} blocks "
          f"bbox x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}] "
          f"z[{min(zs)},{max(zs)}]")
    print(f"  inputs={list(inj)}")
    print(f"  outputs={list(outs)}")
    print(f"  -> {out}")


if __name__ == "__main__":
    main()
