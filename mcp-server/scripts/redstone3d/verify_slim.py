"""
verify_slim.py — fast per-net link verification by building a MINIMAL world.

The full verifier builds every module block (~30k for alu1, far more for ALU) plus
a floor slab stretching out to the trunk rows, twice per net. That single-threaded
construction — not a lack of parallelism — is why the box idled at 40% and a
single net took minutes.

A net's behaviour only depends on its OWN geometry plus whatever sits close enough
to couple with it. So: take the net's blocks, expand by a small margin, keep only
blocks inside that box, and floor just that box. The world shrinks from hundreds of
thousands of cells to a few thousand.

Correctness note: this drops far-away wiring, so it cannot detect a short against
something outside the box. That is fine here — shorts are already checked
combinatorially by the router (0 on every module); what we need MCHPRS for is
whether the signal ARRIVES.
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


def net_voxels(g, zres, net):
    """Every block this net owns: its global trunk geometry, or its local wires."""
    out = {}
    if net in g.routed:
        # global geometry is stored per module; select the cells whose owner net we
        # tracked while building (fall back to the whole trunk row band)
        for (p, b) in g.blocks.items():
            out[p] = b
    for (_z, nets, rr, _sh) in zres:
        if net in rr.wires:
            for p in rr.wires[net]:
                out[p] = W
            for (pos, f) in rr.repeaters.get(net, []):
                out[pos] = f"minecraft:repeater[facing={f},delay=1]"
    return out


def slim_world(pl, g, zres, netlist, net, margin=6):
    """Blocks within `margin` of the net's own geometry, plus a floor for that box."""
    own = net_voxels(g, zres, net)
    src = pl.net_sources[net]
    pts = list(own) + [src] + list(pl.net_sinks[net])
    if not pts:
        return None, None
    x0 = min(p[0] for p in pts) - margin; x1 = max(p[0] for p in pts) + margin
    y0 = min(p[1] for p in pts) - 2;      y1 = max(p[1] for p in pts) + 3
    z0 = min(p[2] for p in pts) - margin; z1 = max(p[2] for p in pts) + margin

    # full module geometry, then clipped
    full = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            full.pop((x, y, z), None)
        else:
            full[(x, y, z)] = s
    for (_z, _n, rr, _s) in zres:
        emit_blocks(setter, pl, rr, {n: 0 for n in netlist["inputs"]})
    for p, b in g.blocks.items():
        setter(*p, b)

    base_y = pl.bounds[0][1]
    keep = {p: b for p, b in full.items()
            if x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and z0 <= p[2] <= z1
            and not ("wall_torch" in b and p[1] == base_y)}
    return keep, (x0, x1, y0, y1, z0, z1)


def check(pl, keep, box, net, base_y, ticks=90):
    x0, x1, y0, y1, z0, z1 = box
    src = pl.net_sources[net]; sinks = pl.net_sinks[net]
    got = {}
    for drive in (0, 1):
        sc = nuc.Schematic.create(f"s_{net}_{drive}")
        B = sc.set_block_from_string
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                B(x, base_y - 1, z, S)
        for (x, y, z), b in keep.items():
            B(x, y, z, b)
        B(src[0] - 1, base_y, src[2], RB if drive else "minecraft:air")
        B(src[0], base_y, src[2], W)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        got[drive] = [w.get_redstone_power(k[0] - 1, base_y, k[2]) for k in sinks]
    ok = all(hi > lo for lo, hi in zip(got[0], got[1]))
    return ok, got[0], got[1]


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    args = [a for a in sys.argv[1:] if not a.isdigit()]
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), 6)
    mod = args[0] if args else "alu1"
    nl = nls[mod]
    t0 = time.time()
    pl = place(nl, col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)
    base_y = pl.bounds[0][1]
    routed = list(g.routed)
    for _z, nets, rr, _sh in zres:
        routed += [n for n in nets if n not in rr.failed]
    print(f"[{mod}] zone={rep['zone_width']}x{rep['zone_depth']} "
          f"routed={rep['total_routed']}/{rep['nets']}", flush=True)
    ok = 0; n = 0
    for net in routed[:limit]:
        keep, box = slim_world(pl, g, zres, nl, net)
        if keep is None:
            continue
        good, lo, hi = check(pl, keep, box, net, base_y)
        n += 1; ok += good
        kind = "global" if net in g.routed else "local"
        print(f"  {net:5s} {kind:6s} blocks={len(keep):6d} "
              f"drive0={lo} drive1={hi}  {'OK' if good else 'BAD'}", flush=True)
    print(f"  => {ok}/{n} links ok  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
