"""
win_net3d.py — follow one net's 3-D wire from source to each sink feed,
printing the power and role at every cell along the parent-tree path. The
first cell whose power drops to 0 is the break.
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import pathfinder3d as PF
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def main():
    nets_want = set(sys.argv[1].split(",")) if len(sys.argv) > 1 else {"n5"}
    nls = json.load(open(NETLISTS))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    PF.RISE_COST = 10.0
    PF.DROP_COST = 8.0
    pf = PF.PathFinder3D(pl, margin=16, max_layers=3, p_cap=128.0)
    placements, shorts = pf.route(max_rounds=30, verbose=False,
                                  start_layers=2)
    print(f"route: shorts={shorts} nets={len(placements)}", flush=True)
    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})

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
    w.tick(120)

    def P(x, y, z):
        return w.get_redstone_power(x, y, z)

    rep_map = {}
    for n, reps in res.repeaters.items():
        for (pos, f) in reps:
            rep_map[pos] = (n, f)
    wire_map = {}
    for n, ws in res.wires.items():
        for p in ws:
            wire_map[p] = n
    # via block/support positions
    blk_map = {}
    for n, ps in placements.items():
        for role, x, y, z, *rest in ps:
            if role in ("block", "rep"):
                blk_map[(x, y, z)] = n

    for net in sorted(nets_want):
        if net not in placements:
            print(f"{net}: no placements", flush=True)
            continue
        src = pl.net_sources[net]
        print(f"\n=== {net}: src={src} pwr={P(*src)} dust="
              f"{sum(1 for p in placements[net] if p[0]=='dust')} "
              f"reps={len(res.repeaters.get(net, []))}", flush=True)
        for pos, f in res.repeaters.get(net, []):
            print(f"    repeater @{pos} facing={f} pwr={P(*pos)}", flush=True)
        # parent BFS over the net's own 3-D cells
        cells = {(p[1], p[2], p[3]) for p in placements[net]
                 if p[0] == "dust"}
        rep_x3 = {pos for (pos, _f) in res.repeaters.get(net, [])}
        all3 = cells | rep_x3
        H3 = [(1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1),
              (0, 1, 0), (0, -1, 0)]
        start = src
        depth = {start: 0}
        par = {}
        q = deque([start])
        while q:
            cur = q.popleft()
            for dx, dy, dz in H3:
                nx = (cur[0] + dx, cur[1] + dy, cur[2] + dz)
                if nx in depth:
                    continue
                if nx in all3:
                    depth[nx] = depth[cur] + 1
                    par[nx] = cur
                    q.append(nx)
        for k in pl.net_sinks[net]:
            feed = (k[0] - 1, pf.y0, k[2])
            print(f"  sink pin={k} feed={feed} pwr={P(*feed)}", flush=True)
            if feed not in depth:
                print(f"    feed NOT reachable in 3-D walk!", flush=True)
                continue
            path = []
            cur = feed
            while cur != start:
                path.append(cur)
                cur = par.get(cur)
                if cur is None:
                    break
            path.reverse()
            for (x, y, z) in path:
                role = "R" if (x, y, z) in rep_map else "w"
                pwr = P(x, y, z)
                print(f"    {role} ({x},{y},{z}) pwr={pwr}", flush=True)


if __name__ == "__main__":
    main()
