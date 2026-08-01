"""
verify_par.py — parallel MCHPRS link verification, sized for the Win box (32
threads).

The serial verifier builds two ~30k-block worlds per net on ONE core, so a module
with 200 nets is hopeless. Each net's check is completely independent (its own
world, its own driver), so they fan out across processes. The routed geometry is
computed once in the parent and handed to the workers.

Usage:
  E:\\py312\\python.exe verify_par.py [--jobs N] [--nets K] MODULE [MODULE...]
"""
from __future__ import annotations
import sys, os, json, time, argparse
import multiprocessing as mp

BASE = os.path.dirname(os.path.abspath(__file__))

# filled in each worker by _init
_G = {}


def _init(blocks_items, srcs, sinks, base_y):
    # blocks_items arrives PRE-FILTERED (gate output torches already removed), so
    # each task skips re-scanning 30k entries for the mask condition.
    _G["blocks"] = blocks_items
    _G["srcs"] = srcs
    _G["sinks"] = sinks
    _G["base_y"] = base_y
    sys.path.insert(0, BASE)
    sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))


def _check(net):
    """Drive one net's source, read each sink's west feed cell."""
    import nucleation as nuc
    RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"
    blocks = _G["blocks"]; base_y = _G["base_y"]
    sx, sz = _G["srcs"][net]
    sinks = _G["sinks"][net]
    got = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"p_{net}_{drive}")
        for (x, y, z, s) in blocks:
            sc.set_block_from_string(x, y, z, s)
        sc.set_block_from_string(sx - 1, base_y, sz,
                                 RB if drive else "minecraft:air")
        sc.set_block_from_string(sx, base_y, sz, W)
        # io_only=True: the redpiler keeps only nodes reachable from the IO
        # (inputs/outputs + the driven net), so the world collapses from the full
        # layout (~90k voxels, 3.5 GB) to the net's chain. With io_only=False
        # every net's verification built the WHOLE 324x88x32 world and MCHPRS
        # died allocating 4 GB per worker (measured on Win: 8 workers x 4 GB).
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(80)
        got[drive] = [w.get_redstone_power(kx - 1, base_y, kz)
                      for (kx, kz) in sinks]
    ok = all(hi > lo for lo, hi in zip(got[0], got[1]))
    return {"net": net, "ok": ok, "drive0": got[0], "drive1": got[1]}


def verify(mod, nl, jobs, limit=None):
    from placer import place
    from build_from_route import emit_blocks
    from route_global_first import route_adaptive
    t0 = time.time()
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)

    blocks = {}
    def raw(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    # Local routing and the cell library go through a GUARDED setter: writes into
    # a reserved gadget cell are dropped and recorded, so a broken delivery is
    # reported with its culprit instead of having to be hunted down by bisection.
    guarded = g.rmap.guarded_setter(raw, writer="local")
    for (_z, _nets, rr, _sh) in zres:
        emit_blocks(guarded, pl, rr, {n: 0 for n in nl["inputs"]})
    for (x, y, z), b in g.blocks.items():
        raw(x, y, z, b)
    viol = g.rmap.audit(blocks)
    if viol:
        print(f"# RESERVE AUDIT: {len(viol)} violation(s), first 8:", flush=True)
        for v in viol[:8]:
            print(f"#   {v}", flush=True)
    else:
        print(f"# RESERVE AUDIT: clean  {g.rmap.summary()}", flush=True)

    routed = list(g.routed)
    for _z, nets, rr, _sh in zres:
        routed += [n for n in nets if n not in rr.failed]
    if limit:
        routed = routed[:limit]

    # Pre-filter once: drop GATE output torches (base plane) so no worker has to
    # test the condition 30k times. The 2x2 down-tower rungs are wall torches too
    # and must be KEPT, which is why the filter is height-based.
    base_y0 = pl.bounds[0][1]
    items = [(x, y, z, s) for (x, y, z), s in blocks.items()
             if not ("wall_torch" in s and y == base_y0)]
    srcs = {n: (pl.net_sources[n][0], pl.net_sources[n][2]) for n in routed}
    sinks = {n: [(k[0], k[2]) for k in pl.net_sinks[n]] for n in routed}
    base_y = pl.bounds[0][1]

    ok = 0; bad = []
    with mp.Pool(processes=jobs, initializer=_init,
                 initargs=(items, srcs, sinks, base_y)) as pool:
        for res in pool.imap_unordered(_check, routed, chunksize=1):
            if res["ok"]:
                ok += 1
            else:
                res["kind"] = "global" if res["net"] in g.routed else "local"
                bad.append(res)
    return {"module": mod, "gates": len(nl["cells"]),
            "zone": f"{rep['zone_width']}x{rep['zone_depth']}",
            "routed": rep["total_routed"], "nets": rep["nets"],
            "blocks": len(blocks), "links_ok": ok, "links_total": len(routed),
            "bad": bad[:10], "jobs": jobs, "secs": round(time.time() - t0, 1)}


def main():
    ap = argparse.ArgumentParser()
    # Oversubscribe by default: each task spends a big share of its time in
    # single-threaded Python (30k set_block calls) and in world setup, so with one
    # worker per core the box idled around 40%. Running ~2x the core count keeps
    # every core busy through those gaps.
    ap.add_argument("--jobs", type=int, default=(os.cpu_count() or 4) * 2)
    ap.add_argument("--nets", type=int, default=0)
    ap.add_argument("mods", nargs="*")
    a = ap.parse_args()
    sys.path.insert(0, BASE)
    sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    for mod in (a.mods or ["alu1"]):
        try:
            print(json.dumps(verify(mod, nls[mod], a.jobs,
                                    a.nets or None), ensure_ascii=False),
                  flush=True)
        except Exception as e:
            print(json.dumps({"module": mod,
                              "error": f"{type(e).__name__}: {e}"}), flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    main()
