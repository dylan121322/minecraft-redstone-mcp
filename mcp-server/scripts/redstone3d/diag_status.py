"""
diag_status.py — one honest snapshot of where alu1 stands, and WHAT is wrong,
before any more fixing.

Two counts have been disagreeing and that confusion is itself a problem:
  * the sweep reports "unfed SINKS" (per pin)
  * _materialize reports "failed NETS" (a net fails if ANY of its sinks fails)
and MCHPRS reports the only thing that ultimately matters: does the truth table
pass. This prints all three from the same route, plus a breakdown of WHY each
failing net fails, so the remaining work is visible rather than guessed.
"""
import sys, os, json
from collections import deque, Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

ORTH, DIAG = coupling.ORTH, coupling.DIAG
CONN = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0),
        (1, 1, 0), (-1, 1, 0), (0, 1, 1), (0, 1, -1),
        (1, -1, 0), (-1, -1, 0), (0, -1, 1), (0, -1, -1))


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


def component(vox, src):
    seed = (src[0], src[1], src[2])
    frontier = [v for v in vox
                if abs(v[0]-seed[0]) + abs(v[1]-seed[1]) + abs(v[2]-seed[2]) == 1]
    comp = set(frontier); dq = deque(frontier)
    while dq:
        cur = dq.popleft()
        for d in CONN:
            q = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
            if q in vox and q not in comp:
                comp.add(q); dq.append(q)
    return comp


def main():
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n13+n14+n8").split("+"))
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
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
    res = r.route(verbose=False, max_rounds=rounds)

    nets = [n for n in pl.net_sinks if pl.net_sources.get(n)]
    total_sinks = sum(len(pl.net_sinks[n]) for n in nets)

    # per-net diagnosis
    reasons = Counter()
    detail = []
    unfed_sinks = 0
    for n in nets:
        vox = set(res.wires.get(n, ())) | {p for (p, _f) in res.repeaters.get(n, ())}
        src = pl.net_sources[n]
        comp = component(vox, src) if vox else set()
        bad = []
        for k in pl.net_sinks[n]:
            feed = (k[0]-1, pl.bounds[0][1], k[2])
            if feed not in comp:
                bad.append((k[0], k[2]))
                unfed_sinks += 1
        if not bad:
            continue
        # classify
        if not vox:
            why = "no routing at all"
        elif not comp:
            why = "routing exists but nothing touches the source"
        else:
            owned_feeds = [(k[0]-1, k[2]) for k in pl.net_sinks[n]
                           if (k[0]-1, pl.bounds[0][1], k[2]) in
                           {(v[0], v[2]) for v in vox} or True]
            has_iso = any((k[0]-1, pl.bounds[0][1], k[2]) in vox and
                          (k[0]-1, pl.bounds[0][1], k[2]) not in comp
                          for k in pl.net_sinks[n])
            why = ("feed cell exists but is DISCONNECTED (isolated wire)"
                   if has_iso else "no wire reaches the feed cell")
        reasons[why] += 1
        detail.append((n, len(pl.net_sinks[n]), bad, why, len(vox), len(comp)))

    print(f"=== alu1 status (yield={sorted(yields)}) ===")
    print(f"nets: {len(nets)}   sinks: {total_sinks}")
    print(f"router-reported failed nets: {len(res.failed)}")
    print(f"recomputed failing nets:     {len(detail)}")
    print(f"unfed sinks:                 {unfed_sinks}/{total_sinks}")
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
    print(f"interfering pairs (measured): {coupling.count_shorts(occ)}")
    print(f"wires={res.total_wires()} conductors={len(occ)}")

    print(f"\n=== why nets fail ===")
    for why, cnt in reasons.most_common():
        print(f"  {cnt:3d} nets: {why}")

    print(f"\n=== per-net detail (first 16) ===")
    for (n, nsink, bad, why, nvox, ncomp) in detail[:16]:
        print(f"  {n:5s} {len(bad)}/{nsink} sinks bad  vox={nvox:4d} "
              f"comp={ncomp:4d}  {why}")
        print(f"        bad sinks: {bad[:4]}")


if __name__ == "__main__":
    main()
