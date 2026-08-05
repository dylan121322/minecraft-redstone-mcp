"""
verify_global_first.py — MCHPRS verification of the global-first flow.

Routing now reports 100% of nets with zero shorts on all seven modules, but that
is only the necessary condition: it says the wires do not touch, not that the
signal arrives. This builds the MERGED geometry (global trunks + per-zone local
routing + gate cells) and drives every net at its source, checking that each sink
RESPONDS (higher power when driven).

Judged by response rather than absolute level: on a module whose gate inputs are
not all driven, a floating gate's output torch is lit and biases nearby wires, so
absolute readings are meaningless while individual nets are tested in isolation.

Runs happily on the Win box (faster); pass module names as arguments.
"""
from __future__ import annotations
import sys, os, json, time
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))

import nucleation as nuc
from placer import place
from build_from_route import emit_blocks
from route_global_first import route_adaptive

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"; S = "minecraft:stone"


def merged_blocks(pl, g, zres, netlist):
    """Gate cells + global trunk geometry + every zone's local routing."""
    blocks = {}

    def setter(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s

    # local routing of each zone also emits the cells and the floor, so emit the
    # first zone fully and merge the rest's wiring on top.
    for i, (_z, _nets, rr, _sh) in enumerate(zres):
        emit_blocks(setter, pl, rr, {n: 0 for n in netlist["inputs"]})
    # global trunks last: they own their columns
    for (x, y, z), b in g.blocks.items():
        setter(x, y, z, b)
    return blocks


def link_check(blocks, pl, net, base_y, ticks=400, global_torches=frozenset()):
    """Drive the net's source; read each sink's west feed cell."""
    src = pl.net_sources[net]
    sinks = pl.net_sinks[net]
    sx, sz = src[0], src[2]
    got = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"v_{net}_{drive}")
        for (x, y, z), s in blocks.items():
            # Mask only the GATE output torches (y == base_y, which is where
            # cell_library puts them). The global delivery towers are ALSO built
            # from wall torches and some land at base_y — masking every wall
            # torch cut every tower's bottom rung, so every global sink stayed
            # dark (measured: the sealed tower responds, the merged layout
            # didn't, and the only difference was the tower's (14,0,15) rung
            # torch missing). Torches that came from the global layout are the
            # delivery hardware, never the gate outputs — keep them.
            if "wall_torch" in s and y == base_y \
                    and (x, y, z) not in global_torches:
                continue
            sc.set_block_from_string(x, y, z, s)
        sc.set_block_from_string(sx - 1, base_y, sz,
                                 RB if drive else "minecraft:air")
        sc.set_block_from_string(sx, base_y, sz, W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        got[drive] = [w.get_redstone_power(k[0] - 1, base_y, k[2]) for k in sinks]
    ok = all(hi > lo for lo, hi in zip(got[0], got[1]))
    return ok, got[0], got[1]


def verify(mod, nl, limit=None):
    t0 = time.time()
    import os
    _rg = int(os.environ.get("ROW_GAP", "16"))
    pl = place(nl, col_gap=16, row_gap=_rg)
    rep, r, g, zres = route_adaptive(pl)
    blocks = merged_blocks(pl, g, zres, nl)
    base_y = pl.bounds[0][1]

    routed = list(g.routed)
    for _z, nets, rr, _sh in zres:
        routed += [n for n in nets if n not in rr.failed]
    if limit:
        routed = routed[:limit]

    ok = 0
    bad = []
    # torch cells that belong to the ROUTED layout (global delivery towers AND
    # local bridge towers) — the gate-output mask must not remove them, or the
    # towers' bottom rungs vanish and every bridged sink goes dark/static
    # (measured: n22/n23 read a frozen 15 with their tower rung torch masked)
    global_torches = frozenset((x, y, z) for (x, y, z), b in g.blocks.items()
                               if "wall_torch" in b and y == base_y)
    for _z, _nets, rr, _sh in zres:
        for (pos, _f) in (rr.wall_torches or ()):
            if pos[1] == base_y:
                global_torches = global_torches | {pos}
    for net in routed:
        good, lo, hi = link_check(blocks, pl, net, base_y,
                                  global_torches=global_torches)
        ok += good
        if not good:
            bad.append({"net": net, "drive0": lo, "drive1": hi,
                        "kind": "global" if net in g.routed else "local"})
    return {"module": mod, "gates": len(nl["cells"]),
            "zone": f"{rep['zone_width']}x{rep['zone_depth']}",
            "routed": rep["total_routed"], "nets": rep["nets"],
            "blocks": len(blocks),
            "links_ok": ok, "links_total": len(routed),
            "bad": bad[:10], "secs": round(time.time() - t0, 1)}


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    args = [a for a in sys.argv[1:] if not a.isdigit()]
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    mods = args or ["alu1"]
    for mod in mods:
        try:
            r = verify(mod, nls[mod], limit=limit)
            print(json.dumps(r, ensure_ascii=False), flush=True)
        except Exception as e:
            print(json.dumps({"module": mod,
                              "error": f"{type(e).__name__}: {e}"}), flush=True)


if __name__ == "__main__":
    main()
