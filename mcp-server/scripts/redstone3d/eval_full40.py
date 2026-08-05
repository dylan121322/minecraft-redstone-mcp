"""
eval_full40.py — score candidate yield-sets on the FULL 40-vector truth table.

The sampled sweep (every k-th vector) has been misleading: it ranked n13+n17 and
n8 both at "8/20", but on all 40 vectors n8 gives both-correct 16/40 while n13+n17
gives 10/40 — and cout is MOVING under n8 yet STUCK under n13+n17. Sampling every
k-th vector skews toward particular ops, so final comparisons must use all 40.

Reports per candidate: y correct, cout correct, both correct, and whether each
output is stuck (a stuck output means a floating gate input somewhere in its cone).
"""
import sys, os, json, time
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _eval(args):
    mod, yields, rounds, ticks = args
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
    ys = set(yields)
    if ys:
        orig = r._route_once
        def patched(nets, soft=False, verbose=False):
            head = [n for n in nets if n not in ys]
            tail = [n for n in nets if n in ys]
            return orig(head + tail, soft=soft, verbose=verbose)
        r._route_once = patched
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

    ny = nc = both = 0
    yv_set = set(); cv_set = set()
    per_op = {}
    for op in (0, 1, 2, 3, 6):
        okop = 0
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
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
                    yv_set.add(yv); cv_set.add(cv)
                    bb = (1 - bv) if op == 6 else bv
                    summ = a ^ bb ^ cin
                    cout = (a & bb) | (cin & (a ^ bb))
                    ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv,
                          6: summ}.get(op, 0)
                    ny += (yv == ey); nc += (cv == cout)
                    g = (yv == ey and cv == cout)
                    both += g; okop += g
        per_op[op] = okop
    return {"yields": list(yields), "y_ok": ny, "c_ok": nc, "both": both,
            "y_stuck": len(yv_set) == 1, "c_stuck": len(cv_set) == 1,
            "per_op": per_op, "shorts": shorts, "failed": len(res.failed),
            "failed_nets": res.failed[:8], "wires": res.total_wires(),
            "secs": round(_t.time()-t0, 1)}


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    cands = (sys.argv[4] if len(sys.argv) > 4
             else "-,n8,n13,n13+n17,n13+n7,n5,n25,n13+n5").split(",")
    ticks = int(sys.argv[5]) if len(sys.argv) > 5 else 80
    jobs = []
    for c in cands:
        ys = tuple(t for t in c.split("+") if t and t != "-")
        jobs.append((mod, ys, rounds, ticks))
    print(f"FULL 40-vector evaluation: {len(jobs)} candidates, {workers} workers")
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
                rec = {"yields": list(futs[f][1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] {rec['yields']} ERROR "
                      f"{rec['error'][:60]}", flush=True)
            else:
                lbl = "+".join(rec["yields"]) or "-"
                print(f"  [{n}/{len(jobs)}] {lbl:14s} both={rec['both']}/40 "
                      f"y={rec['y_ok']}{'S' if rec['y_stuck'] else ''} "
                      f"c={rec['c_ok']}{'S' if rec['c_stuck'] else ''} "
                      f"sh={rec['shorts']} failed={rec['failed']}", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (-r["both"], r["shorts"], r["wires"]))
    print(f"\n{'yield':14s} {'both':>6s} {'y_ok':>5s} {'c_ok':>5s} "
          f"{'stuck':>7s} {'sh':>3s} {'fail':>4s} {'wires':>6s}  per-op")
    for r in ok:
        lbl = "+".join(r["yields"]) or "-"
        st = ("y" if r["y_stuck"] else "") + ("c" if r["c_stuck"] else "") or "-"
        print(f"{lbl:14s} {str(r['both'])+'/40':>6s} {r['y_ok']:5d} "
              f"{r['c_ok']:5d} {st:>7s} {r['shorts']:3d} {r['failed']:4d} "
              f"{r['wires']:6d}  {r['per_op']}")
    json.dump(ok, open(os.path.join(base, "full40.json"), "w"))
    print("\nsaved full40.json")


if __name__ == "__main__":
    main()
