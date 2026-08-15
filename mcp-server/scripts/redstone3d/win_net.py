"""
win_net.py — follow one net's wire from source to each sink feed, printing
the power at every cell along the parent-tree path. The first cell whose
power drops to 0 is the break: either a misoriented repeater, an unrefreshed
long run, or a wire overwritten by another net's repeater.
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder as PF
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def main():
    nets_want = set((sys.argv[1] if len(sys.argv) > 1 else "n26,n27").split(","))
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    pf = PF.PathFinder(pl, margin=16)
    placements, shorts = pf.route(max_rounds=40, verbose=False)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    y0 = pf.y0

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    iv = {nm(pb["a"][0]): 1, nm(pb["b"][0]): 0, nm(pb["cin"][0]): 0}
    for i in range(4):
        iv[nm(pb["op"][i])] = (3 >> i) & 1
    for inet in nl["inputs"]:
        iv.setdefault(inet, 0)

    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, iv)
    sc = nuc.Schematic.create("t")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(80)

    def P(x, y, z):
        return w.get_redstone_power(x, y, z)

    for net in sorted(nets_want):
        if net not in placements:
            print(f"{net}: no placements", flush=True)
            src = pl.net_sources.get(net)
            if src:
                print(f"    src={src} pwr={P(*src)}", flush=True)
                # who owns the 4 neighbours?
                all_occ = {}
                for m, ps in placements.items():
                    for role, x, y, z in ps:
                        all_occ[(x, z)] = m
                for dx, dz in _H:
                    nx, nz = src[0] + dx, src[2] + dz
                    own = all_occ.get((nx, nz))
                    print(f"    neighbour ({nx},{nz}): "
                          f"{own if own else 'free'}", flush=True)
            continue
        src = pl.net_sources[net]
        print(f"\n=== {net}: source={src} pwr={P(*src)} "
              f"dust={len(placements[net])} reps={len(res.repeaters.get(net, []))}",
              flush=True)
        for pos, f in res.repeaters.get(net, []):
            print(f"    repeater @{pos} facing={f} pwr={P(*pos)}", flush=True)
        # parent BFS over the net's own cells
        cells = {(p[1], p[3]) for p in placements[net] if p[0] == "dust"}
        reps = {p[0:2] + (p[2],): p for p in []}
        rep_xz = {(p[0], p[2]) for (p, _f) in res.repeaters.get(net, [])}
        start = (src[0], src[2])
        depth = {start: 0}
        par = {}
        q = deque([start])
        while q:
            cur = q.popleft()
            for dx, dz in _H:
                nx = (cur[0] + dx, cur[1] + dz)
                if nx in depth:
                    continue
                if nx in cells or nx in rep_xz:
                    depth[nx] = depth[cur] + 1
                    par[nx] = cur
                    q.append(nx)
        for k in pl.net_sinks[net]:
            feed = (k[0] - 1, k[2])
            print(f"  sink pin={k} feed={feed} feed_pwr={P(feed[0], y0, feed[1])}",
                  flush=True)
            # walk path feed -> source
            if feed not in depth:
                print(f"    feed NOT in net's cells!", flush=True)
                continue
            path = []
            cur = feed
            while cur != start:
                path.append(cur)
                cur = par.get(cur)
                if cur is None:
                    break
            path.reverse()
            line = []
            for (x, z) in path[:80]:
                pwr = P(x, y0, z)
                mark = "R" if (x, z) in rep_xz else "."
                line.append(f"{mark}{pwr:2d}")
            print(f"    src->feed: " + " ".join(line), flush=True)


if __name__ == "__main__":
    main()
