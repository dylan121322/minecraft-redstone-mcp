"""route_solve.py — Portfolio negotiated router for one module.

Runs N parallel serial-PathFinder instances with DIFFERENT history-increment
and net-ordering seeds; the first to reach zero congestion wins. This both
saturates cores AND guarantees convergence (adaptive: some seed always works).

Usage: py route_solve.py <name> <netlist.json> <max_iters> [n_variants]
"""
import sys, os, json, time, random
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))   # redstone3d modules live in parent (E:\rs3d)
from placer import place
from maze_router import MazeRouter, RouteResult
from collections import Counter
import multiprocessing as mp


def solve_variant(args):
    """One PathFinder run with (hist_inc, seed, spacing). Returns (ok, wires, iters, hist_inc, pl)."""
    nl, hist_inc, seed, max_iters, spacing = args
    random.seed(seed)
    cg, rg = spacing
    pl = place(nl, col_gap=cg, row_gap=rg)
    r = MazeRouter(pl, margin=max(8, cg))

    nets = [n for n in pl.net_sinks if pl.net_sources.get(n) and pl.net_sinks.get(n)]
    random.shuffle(nets)
    pres = {}; hist = {}; routes = {n: set() for n in nets}

    for it in range(max_iters):
        for net in nets:
            for p in routes[net]:
                pres[p] = pres.get(p, 0) - 1
            routes[net] = set()
            src = pl.net_sources[net]; sinks = pl.net_sinks[net]
            tree = {src}
            for sink in sorted(sinks, key=lambda s: abs(src[0]-s[0])+abs(src[2]-s[2])):
                path = r._cost_bfs(tree, sink, net, pres, hist)
                if path:
                    for p in path:
                        if p not in r.pin_pos:
                            tree.add(p); routes[net].add(p)
            for p in routes[net]:
                pres[p] = pres.get(p, 0) + 1
        cong = [p for p, c in pres.items() if c > 1]
        if not cong:
            return (True, {n: list(routes[n]) for n in nets}, it+1, hist_inc, pl)
        for p in cong:
            hist[p] = hist.get(p, 0.0) + hist_inc
    return (False, {n: list(routes[n]) for n in nets}, max_iters, hist_inc, pl)


def main():
    name = sys.argv[1]; nlj = sys.argv[2]
    max_iters = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    n_var = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    n_var = n_var or (os.cpu_count() or 8)

    nl = json.load(open(os.path.join(HERE, nlj)))
    print(f"[{name}] {len(nl['cells'])} gates, {n_var} parallel variants", flush=True)

    # variants: escalating history increments + WIDER placement spacings.
    # Wider spacing gives the router dedicated channels → far easier to legalize
    # dense modules. Each variant tries a different (hist_inc, spacing, seed).
    hist_incs = [1.0, 2.0, 4.0]
    spacings = [(10, 6), (16, 10), (24, 14)]   # (col_gap, row_gap)
    variants = []
    for i in range(n_var):
        hi = hist_incs[i % len(hist_incs)]
        sp = spacings[(i // len(hist_incs)) % len(spacings)]
        variants.append((nl, hi, 1000 + i, max_iters, sp))

    t = time.time()
    pool = mp.Pool(n_var)
    best = None
    try:
        # imap_unordered → grab first converged, then terminate the rest
        for ok, routes, iters, hinc, pl in pool.imap_unordered(solve_variant, variants):
            if ok:
                best = (routes, iters, hinc, pl)
                print(f"[{name}] CONVERGED via hist_inc={hinc} in {iters} iters "
                      f"({time.time()-t:.1f}s)", flush=True)
                break
            else:
                print(f"[{name}] variant hist_inc={hinc} exhausted {iters} iters, "
                      f"no converge", flush=True)
    finally:
        pool.terminate(); pool.join()

    if not best:
        print(f"[{name}] NO variant converged", flush=True)
        json.dump({"module": name, "status": "FAILED", "time_s": round(time.time()-t,1)},
                  open(os.path.join(HERE, f"{name}_route.json"), "w"))
        return

    routes, iters, hinc, pl = best
    # legality
    own = Counter()
    for net, ws in routes.items():
        for p in ws: own[tuple(p)] += 1
    shared = sum(1 for c in own.values() if c > 1)

    # export litematic
    import nucleation as n
    mn, mx = pl.bounds
    s = n.Schematic.create(name)
    s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mx[0]+3, -1, mx[2]+3, "minecraft:stone")
    for pc in pl.placed.values():
        pc.cell.emit(s, *pc.origin)
    wtotal = 0
    for net, ws in routes.items():
        for p in ws:
            x, y, z = p
            if y > 0: s.set_block_from_string(x, y-1, z, "minecraft:stone")
            s.set_block_from_string(x, y, z, "minecraft:redstone_wire")
            wtotal += 1
    for net, pos in pl.primary_inputs.items():
        s.set_block_from_string(pos[0], pos[1], pos[2], "minecraft:redstone_wire")
    outp = os.path.join(HERE, f"{name}.litematic")
    s.save_to_file(outp)
    dt = time.time() - t
    print(f"[{name}] LEGAL shared={shared} wires={wtotal} → {os.path.getsize(outp)}B "
          f"{s.block_count()} blocks in {dt:.1f}s", flush=True)
    json.dump({"module": name, "gates": len(nl["cells"]), "wires": wtotal,
               "shared": shared, "iters": iters, "hist_inc": hinc,
               "time_s": round(dt, 1), "status": "LEGAL" if shared == 0 else "ILLEGAL"},
              open(os.path.join(HERE, f"{name}_route.json"), "w"))


if __name__ == "__main__":
    main()
