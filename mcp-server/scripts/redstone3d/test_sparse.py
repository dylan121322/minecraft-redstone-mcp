"""test_sparse.py — maximise sparsity: sweep large col_gap/row_gap and measure
routed nets + shorts + truth table. Density = connection demand / area; raising
the gaps lowers density per cell, giving every net more room."""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

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


def _run(args):
    cg, rg = args
    import importlib
    import route_buildable as RB2
    importlib.reload(RB2)
    install_measured()
    import placer
    importlib.reload(placer)
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    pl = place(nls["alu1"], col_gap=cg, row_gap=rg)
    mn, mx = pl.bounds
    r = RB2.BuildableRouter(pl, margin=max(10, cg))
    res = r.route(verbose=False, max_rounds=4)
    sh, _ = r._count_shorts(res)
    own = {}
    for n in res.wires:
        own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                 {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = 0
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own.get(n, set()):
                unfed += 1
    return (cg, rg, f"{mx[0]-mn[0]+1}x{mx[2]-mn[2]+1}", sh, unfed,
            res.total_wires())


def main():
    from concurrent.futures import ProcessPoolExecutor, as_completed
    install_measured()
    configs = [(16, 16), (24, 24), (32, 32), (40, 40), (48, 48),
               (32, 64), (64, 32), (64, 64), (32, 96), (48, 96)]
    print(f"{'cg':>4s} {'rg':>4s} {'bbox':>12s} {'shorts':>6s} {'unfed':>6s} "
          f"{'wires':>6s}", flush=True)
    with ProcessPoolExecutor(max_workers=min(10, os.cpu_count() or 4)) as ex:
        for rec in ex.map(_run, configs):
            cg, rg, bbox, sh, unfed, wires = rec
            print(f"{cg:4d} {rg:4d} {bbox:>12s} {sh:6d} {unfed:6d} "
                  f"{wires:6d}", flush=True)


if __name__ == "__main__":
    main()
