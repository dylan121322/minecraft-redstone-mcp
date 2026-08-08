"""
enum_order.py — the empty-board test proved n2/n3/n14 each route fine ALONE but
fail together: they compete for the same feed cells. The router's yield-set
search only moves nets to the END of the order. The real question is their
RELATIVE order. Enumerate all 6 permutations of {n2, n3, n14} as the TAIL of the
routing order (the rest keep their normal order), and judge each on the truth
table — the winner tells us the order the router should impose.
"""
import sys, os, json, time, itertools
from concurrent.futures import ProcessPoolExecutor, as_completed

base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def _eval(args):
    mod, tail_order, rounds, ticks = args
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
    tail = list(tail_order)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in tail]
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
    for op in (0, 1, 2, 3, 6):
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
                    both += (yv == ey and cv == cout)
    return {"tail": list(tail_order), "both": both, "y_ok": ny, "c_ok": nc,
            "y_stuck": len(yv_set) == 1, "c_stuck": len(cv_set) == 1,
            "shorts": shorts, "failed": len(res.failed),
            "failed_nets": res.failed[:6], "wires": res.total_wires(),
            "secs": round(_t.time() - t0, 1)}


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    workers = int(sys.argv[3]) if len(sys.argv) > 3 else min(32, os.cpu_count() or 8)
    ticks = int(sys.argv[4]) if len(sys.argv) > 4 else 80
    trio = ("n2", "n3", "n14")
    jobs = [(mod, perm, rounds, ticks) for perm in itertools.permutations(trio)]
    # baseline: no tail forcing
    jobs.append((mod, (), rounds, ticks))
    print(f"enumerating tail orders of {trio}: {len(jobs)} runs, {workers} workers")
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
                rec = {"tail": list(futs[f][1]),
                       "error": f"{type(e).__name__}: {e}"}
            out.append(rec)
            if "error" in rec:
                print(f"  [{n}/{len(jobs)}] tail={rec['tail']} ERROR "
                      f"{rec['error'][:50]}", flush=True)
            else:
                lbl = ">".join(rec["tail"]) or "-"
                print(f"  [{n}/{len(jobs)}] {lbl:14s} both={rec['both']}/40 "
                      f"y={rec['y_ok']}{'S' if rec['y_stuck'] else ''} "
                      f"c={rec['c_ok']}{'S' if rec['c_stuck'] else ''} "
                      f"sh={rec['shorts']} failed={rec['failed']} "
                      f"wires={rec['wires']}", flush=True)
    print(f"\nwall-clock {time.time()-t0:.0f}s")
    ok = [r for r in out if "error" not in r]
    ok.sort(key=lambda r: (-r["both"], r["shorts"], r["wires"]))
    print(f"\n{'tail order':14s} {'both':>6s} {'y_ok':>5s} {'c_ok':>5s} "
          f"{'stuck':>7s} {'sh':>3s} {'fail':>4s} {'wires':>6s}")
    for r in ok:
        lbl = ">".join(r["tail"]) or "-"
        st = ("y" if r["y_stuck"] else "") + ("c" if r["c_stuck"] else "") or "-"
        print(f"{lbl:14s} {str(r['both'])+'/40':>6s} {r['y_ok']:5d} "
              f"{r['c_ok']:5d} {st:>7s} {r['shorts']:3d} {r['failed']:4d} "
              f"{r['wires']:6d}")
    json.dump(ok, open(os.path.join(base, "enum_order.json"), "w"))
    print("\nsaved enum_order.json")


if __name__ == "__main__":
    main()
