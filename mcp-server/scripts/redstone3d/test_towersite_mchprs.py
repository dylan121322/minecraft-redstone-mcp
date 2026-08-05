"""
test_towersite_mchprs.py — the fix the enumeration keeps pointing at, judged by
MCHPRS this time.

Enumeration (enum_v2) says n17 has 24 fully viable (climb-site, cross-layer,
rotation) triples — approach verified with the router's own legality rule — yet
the router fails that sink, because _extend_toward/_find_foothold pick the climb
site by DISTANCE TO THE SINK and never test whether the cross layer can reach the
feed column from there. Same story earlier for n6.

Patch: choose the climb anchor among the net's own y0 cells by CROSS-REACHABILITY
(shortest proven approach), falling back to the original when none qualifies.
Judged on the truth table, not on static counts, since static counts have been
unreliable.
"""
import sys, os, json, time
from collections import deque
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


def _eval(args):
    mod, yields, rounds, patched_site, nvec, ticks = args
    import json as _j, importlib, time as _t
    import route_buildable as RB
    importlib.reload(RB)
    import coupling
    importlib.reload(coupling)
    ORTH, DIAG = coupling.ORTH, coupling.DIAG

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

    import placer, build_from_route
    importlib.reload(placer); importlib.reload(build_from_route)
    import nucleation as nuc
    from placer import place
    from build_from_route import emit_blocks

    nls = _j.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)

    if patched_site:
        orig_extend = r._extend_toward

        def cross_reach(src_xz, goal_xz, net, cy, limit=6000):
            if not r._y2_free(src_xz, net, cy):
                return None
            seen = {src_xz}; prev = {}; q = deque([src_xz]); st = 0
            while q and st < limit:
                cur = q.popleft(); st += 1
                if cur == goal_xz:
                    n = 0; c = cur
                    while c in prev:
                        c = prev[c]; n += 1
                    return n
                for dx, dz in _H:
                    nx = (cur[0]+dx, cur[1]+dz)
                    if nx in seen or nx in r.rep_cells:
                        continue
                    if not r._y2_free(nx, net, cy):
                        continue
                    seen.add(nx); prev[nx] = cur; q.append(nx)
            return None

        def patched_extend(net, placements, goal_xz):
            y0 = r.base_y
            cy = r.net_cross_y.get(net, y0 + 4)
            tree = [(p[1], p[3]) for p in placements.get(net, [])
                    if p[0] == "dust" and p[2] == y0]
            s = r.pl.net_sources[net]
            tree.append((s[0], s[2]))
            best = None
            for t in tree:
                d = cross_reach(t, goal_xz, net, cy)
                if d is None:
                    continue
                if best is None or d < best[1]:
                    best = (t, d)
            if best is None:
                return orig_extend(net, placements, goal_xz)
            return (best[0], None, None)

        r._extend_toward = patched_extend

    ys = set(yields)
    if ys:
        orig = r._route_once
        def rpatched(nets, soft=False, verbose=False):
            head = [n for n in nets if n not in ys]
            tail = [n for n in nets if n in ys]
            return orig(head + tail, soft=soft, verbose=verbose)
        r._route_once = rpatched

    t0 = _t.time()
    res = r.route(verbose=False, max_rounds=rounds)

    occ = {}
    for n, ws in res.wires.items():
        for p in ws:
            occ[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occ[q] = n
    for p in res.torches:
        occ[p] = res.torch_nets.get(p, "?")
    for (q, _b) in res.wall_torches:
        occ[q] = res.wall_torch_nets.get(q, "?")
    shorts = coupling.count_shorts(occ)

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))

    tests = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    tests.append((a, bv, cin, op))
    if nvec < len(tests):
        step = max(1, len(tests) // nvec)
        tests = tests[::step][:nvec]

    ok = ny = nc = 0
    for (a, bv, cin, op) in tests:
        iv = {a_n: a, b_n: bv, cin_n: cin}
        for i in range(4):
            iv[op_n[i]] = (op >> i) & 1
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
        w.tick(ticks)
        yv = 1 if w.get_redstone_power(*y_pos) > 0 else 0
        cv = 1 if w.get_redstone_power(*c_pos) > 0 else 0
        bb = (1 - bv) if op == 6 else bv
        summ = a ^ bb ^ cin
        cout = (a & bb) | (cin & (a ^ bb))
        ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv, 6: summ}.get(op, 0)
        ny += (yv == ey); nc += (cv == cout)
        ok += (yv == ey and cv == cout)

    return {"yields": list(yields), "patched": patched_site, "passes": ok,
            "y_ok": ny, "c_ok": nc, "vectors": len(tests), "shorts": shorts,
            "failed": len(res.failed), "failed_nets": res.failed[:6],
            "wires": res.total_wires(), "secs": round(_t.time()-t0, 1)}


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    nvec = int(sys.argv[4]) if len(sys.argv) > 4 else 20
    ticks = int(sys.argv[5]) if len(sys.argv) > 5 else 80
    yl = ["", "n8", "n5", "n3+n5", "n18+n8", "n13+n8"]
    jobs = []
    for y in yl:
        ys = tuple(t for t in y.split("+") if t)
        for pt in (False, True):
            jobs.append((mod, ys, rounds, pt, nvec, ticks))
    print(f"tower-site patch A/B on the TRUTH TABLE: {len(jobs)} runs, "
          f"{nvec} vectors, {workers} workers")
    out = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_eval, j): j for j in jobs}
        n = 0
        for f in as_completed(futs):
            n += 1
            try:
                rec = f.result()
            except Exception as e:
                j = futs[f]
                rec = {"yields": list(j[1]), "patched": j[3],
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] y={rec['yields']} "
                      f"patched={rec['patched']} ERROR {rec['error'][:50]}",
                      flush=True)
            else:
                print(f"  [{n}/{len(jobs)}] y={rec['yields'] or '-'} "
                      f"patched={int(rec['patched'])} "
                      f"PASS={rec['passes']}/{rec['vectors']} "
                      f"(y={rec['y_ok']} c={rec['c_ok']}) "
                      f"sh={rec['shorts']} failed={rec['failed']}", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (-r["passes"], r["shorts"], r["wires"]))
    print(f"\n{'yield':16s} {'patch':5s} {'PASS':>7s} {'y_ok':>5s} {'c_ok':>5s} "
          f"{'sh':>3s} {'failed':>6s} {'wires':>6s}")
    for r in ok:
        print(f"{'+'.join(r['yields']) or '-':16s} {int(r['patched']):5d} "
              f"{str(r['passes'])+'/'+str(r['vectors']):>7s} {r['y_ok']:5d} "
              f"{r['c_ok']:5d} {r['shorts']:3d} {r['failed']:6d} {r['wires']:6d}")
    json.dump(ok, open(os.path.join(base, "towersite_mchprs.json"), "w"))


if __name__ == "__main__":
    main()
