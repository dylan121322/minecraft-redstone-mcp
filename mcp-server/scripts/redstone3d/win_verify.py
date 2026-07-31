"""
win_verify.py — Windows-side MCHPRS verification: route a module, emit the real
geometry, and check every routed net's link electrically (source driven -> each
sink responds). Runs on the Win box because MCHPRS world-building for a whole
module is the slow part; the Mac side keeps code + light checks.

Usage (on Win):
  E:\\py312\\python.exe E:\\project\\scripts\\redstone3d\\win_verify.py alu1 [rounds]

Prints one JSON line per module so the Mac side can collect results.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_buildable import BuildableRouter
from build_from_route import emit_blocks

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def link_check(blocks, pl, net, base_y):
    """Drive the net's published source, read every sink's west feed cell.
    Gate output torches are masked: on a partially routed module a gate with an
    unrouted input floats and its lit torch biases nearby wires."""
    src = pl.net_sources[net]
    sinks = pl.net_sinks[net]
    sx, sz = src[0], src[2]
    read = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"lk_{net}_{drive}")
        for (x, y, z), s in blocks.items():
            if "wall_torch" in s:
                continue
            sc.set_block_from_string(x, y, z, s)
        sc.set_block_from_string(sx - 1, base_y, sz,
                                 RB if drive else "minecraft:air")
        sc.set_block_from_string(sx, base_y, sz, W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(60)
        read[drive] = [w.get_redstone_power(k[0] - 1, base_y, k[2]) for k in sinks]
    good = all(h > l for l, h in zip(read[0], read[1]))
    return good, read[0], read[1]


def verify(mod, rounds=4):
    t0 = time.time()
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    shorts, _ = r._count_shorts(res)
    base_y = pl.bounds[0][1]
    blocks = {}

    def setter(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 0 for n in nl["inputs"]})

    routed = [n for n in pl.net_sinks
              if n not in res.failed and pl.net_sources.get(n) and pl.net_sinks.get(n)]
    ok = 0; bad = []
    for net in routed:
        g, lo, hi = link_check(blocks, pl, net, base_y)
        ok += g
        if not g:
            bad.append({"net": net, "drive0": lo, "drive1": hi})
    return {
        "module": mod, "gates": len(nl["cells"]),
        "nets": len(routed) + len(res.failed),
        "routed": len(routed), "failed": len(res.failed),
        "shorts": shorts, "blocks": len(blocks),
        "links_ok": ok, "links_total": len(routed),
        "bad": bad[:8], "secs": round(time.time() - t0, 1),
    }


if __name__ == "__main__":
    mods = [a for a in sys.argv[1:] if not a.isdigit()] or ["alu1"]
    rounds = next((int(a) for a in sys.argv[1:] if a.isdigit()), 4)
    for m in mods:
        try:
            print(json.dumps(verify(m, rounds), ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"module": m, "error": f"{type(e).__name__}: {e}"}),
                  flush=True)
