"""
size_full_space.py — size the FULL enumeration space: for every sink of alu1,
count the delivery candidates (stair offsets x cross layers x tower rotations)
that are geometrically viable. The product is the upper bound; we then decide
what to prune to make an exhaustive search tractable.
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
DZS = (0, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8)


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]
    layers = [y0 + 4 * i for i in range(1, 7)]

    # empty-board viability: count per sink how many delivery candidates fit
    # geometrically (not competing with anything — the pure upper bound)
    total_sinks = 0
    per_net = {}
    grand_total = 1
    for net, ks in sorted(pl.net_sinks.items()):
        if not pl.net_sources.get(net):
            continue
        n_sinks = len(ks)
        total_sinks += n_sinks
        per_sink = []
        for k in ks:
            gx, gz = k[0], k[2]
            feed = (gx - 1, gz)
            n_cand = 0
            for cy in layers:
                # stairs: depth = cy+1-y0 cells west from gx on row gz+dz
                for dz in DZS:
                    depth = cy + 1 - y0
                    cells = [(gx - depth + i, gz + dz) for i in range(1, depth + 1)]
                    if any(c in pl.occupancy or c in [(p[0], p[2]) for p in
                             [v for vs in pl.net_sinks.values() for v in vs]]
                           for c in cells):
                        continue
                    n_cand += 1
                # towers
                for arm, side in ROTS:
                    cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                                       side=side, arm=arm)
                    if any(c in pl.occupancy for c in foot):
                        continue
                    n_cand += 1
            per_sink.append(n_cand)
        per_net[net] = (n_sinks, per_sink)
        prod = 1
        for c in per_sink:
            prod *= max(1, c)
        print(f"  {net:5s}: {n_sinks} sinks, candidates {per_sink}, "
              f"combo={prod}")
        grand_total *= prod
    print(f"\ntotal sinks: {total_sinks}")
    print(f"joint space (upper bound, before competition pruning): "
          f"{grand_total:.3e}")
    print(f"per-net combos: {[(n, p) for n, (ns, p) in per_net.items()]}")


if __name__ == "__main__":
    main()
