"""
diag_n3_break.py — MCHPRS showed the fully-routed alu1 delivers power to almost
every sink (n4: 10/10, n5: 14/14, n3: 0/9/6/6) — only n3's sink at (18,17) reads
0. Find where n3's path to that sink loses power, across ALL layers (its route
uses a bridge, so the y0-only walk missed most of it).

Dump every conductor n3 owns, sorted by distance along the route, with its
measured power, so the exact break shows up.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
import route_buildable as RB
import coupling
from build_from_route import emit_blocks

ORTH, DIAG = coupling.ORTH, coupling.DIAG


def install_measured():
    def _foreign_plane(self, xz, net, owner):
        x, z = xz
        for dx, dz in ORTH:
            o = owner.get((x + dx, z + dz))
            if o is not None and o != net:
                return True
        for dx, dz in DIAG:
            o = owner.get((x + dx, z + dz))
            if o is None or o == net:
                continue
            if (x + dx, z) in owner or (x, z + dz) in owner:
                return True
        return False
    SH = [(dx, 0, dz) for dx, dz in ORTH] + [(0, 1, 0), (0, -1, 0)] + \
         [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    RB.BuildableRouter._foreign_plane = _foreign_plane
    RB.BuildableRouter._SHELL3D = SH


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n3"
    sink_z = int(sys.argv[2]) if len(sys.argv) > 2 else 17
    yields = set((sys.argv[3] if len(sys.argv) > 3 else "n18+n3+n6").split("+"))
    ticks = int(sys.argv[4]) if len(sys.argv) > 4 else 80

    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yields]
        tail = [n for n in nets if n in yields]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=5)

    iv = {n: 1 for n in nl["inputs"]}
    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, iv)
    sc = nuc.Schematic.create("brk")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)

    src = pl.net_sources[net]
    print(f"{net} source={src}  target sink z={sink_z}")
    own = sorted(res.wires.get(net, ()))
    reps = {q: f for (q, f) in res.repeaters.get(net, ())}
    print(f"{net} conductors: {len(own)} wires + {len(reps)} repeaters")

    # group by layer and report power, focusing on the rows near the sink
    from collections import defaultdict
    bylayer = defaultdict(list)
    for p in own:
        bylayer[p[1]].append(p)
    for q in reps:
        bylayer[q[1]].append(q)
    for y in sorted(bylayer):
        cells = sorted(bylayer[y])
        live = [(p, w.get_redstone_power(*p)) for p in cells]
        on = [p for p, v in live if v > 0]
        off = [p for p, v in live if v == 0]
        print(f"  y={y}: {len(cells)} cells, live={len(on)} dead={len(off)}")
        if off:
            print(f"     dead sample: {off[:8]}")

    # walk the neighbourhood of the failing feed
    feed = None
    for k in pl.net_sinks[net]:
        if k[2] == sink_z:
            feed = (k[0] - 1, k[1], k[2])
    if feed:
        print(f"\nneighbourhood of failing feed {feed}:")
        for dy in (2, 1, 0, -1):
            for dz in (-1, 0, 1):
                row = []
                for dx in (-3, -2, -1, 0, 1):
                    q = (feed[0]+dx, feed[1]+dy, feed[2]+dz)
                    s = rec.get(q)
                    if not s:
                        row.append("  .")
                        continue
                    tag = ("W" if "wire" in s else "R" if "repeater" in s
                           else "T" if "torch" in s else "#" if s.endswith("stone")
                           else "?")
                    row.append(f"{tag}{w.get_redstone_power(*q):2d}")
                print(f"   dy={dy:+d} dz={dz:+d}: " + " ".join(row))


if __name__ == "__main__":
    main()
