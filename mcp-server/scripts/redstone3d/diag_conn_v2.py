"""
diag_conn_v2.py — the connectivity test itself is wrong, not (necessarily) the
routing.

Evidence from n4: 299 voxels, only 1 reachable. Its geometry around the source is

    y=0 : ... wire(x=0, the PI) | rep(x=1, net-owned) | stone(x=2)
    y=1 :                                               torch
    y=2 :                                               stone

i.e. a normal 1x1 climb tower: the repeater strongly powers the tower's base
BLOCK, the standing torch above it inverts, and so on up to the cross plane. That
conducts in Minecraft — but the BFS only walked `wires + repeaters`, and a
tower's rungs are STONE blocks and TORCHES, which were not in the node set. So
the walk stopped at the repeater and declared 298 orphans.

This version includes supports and torches as conducting nodes with the right
adjacency (a torch powers the block above it; a powered block powers dust on top
and beside it) and re-counts, to separate "really broken" from "wrongly judged".
"""
import sys, os, json
from collections import deque, Counter
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


def reach(src, wires, reps, torches, wtorch, supports):
    """Walk the net's structure the way power actually flows.

    node kinds:
      dust      : links to dust/rep orthogonally, plus see-below/ramp (dy=+-1
                  with one horizontal step), and to a support directly under it
      repeater  : links along its facing axis (we accept both, orientation is
                  checked elsewhere) and strongly powers an adjacent block
      support   : a powered block links to dust on top of it and to a torch
                  standing on it
      torch     : powers the block above it and dust beside it
    """
    nodes = set(wires) | set(reps) | set(torches) | set(wtorch) | set(supports)
    seed = [v for v in nodes
            if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
    comp = set(seed); dq = deque(seed)
    H = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))
    while dq:
        cur = dq.popleft()
        cand = []
        cand += [(cur[0]+d[0], cur[1]+d[1], cur[2]+d[2]) for d in H]
        cand.append((cur[0], cur[1]+1, cur[2]))     # up (torch->block, block->dust)
        cand.append((cur[0], cur[1]-1, cur[2]))     # down (dust->support)
        for d in H:                                  # see-below / ramp
            cand.append((cur[0]+d[0], cur[1]+1, cur[2]+d[2]))
            cand.append((cur[0]+d[0], cur[1]-1, cur[2]+d[2]))
        for q in cand:
            if q in nodes and q not in comp:
                comp.add(q); dq.append(q)
    return comp, nodes


def main():
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n13+n14+n8").split("+"))
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

    # torches/supports are global lists, so attribute them per net by proximity
    # to the net's own voxels (a tower's rungs sit in the net's own column).
    nets = [n for n in pl.net_sinks if pl.net_sources.get(n)]
    y0 = pl.bounds[0][1]
    tn = res.torch_nets; wn = res.wall_torch_nets
    still_bad = []
    fixed = []
    for n in nets:
        wires = set(res.wires.get(n, ()))
        reps = {p for (p, _f) in res.repeaters.get(n, ())}
        torches = {p for p in res.torches if tn.get(p) == n}
        wtorch = {p for (p, _b) in res.wall_torches if wn.get(p) == n}
        # supports are unattributed; take those adjacent to this net's own voxels
        mine = wires | reps | torches | wtorch
        cols = {(p[0], p[2]) for p in mine}
        supports = {s for s in res.supports if (s[0], s[2]) in cols}
        src = pl.net_sources[n]
        comp, nodes = reach(src, wires, reps, torches, wtorch, supports)
        bad = []
        for k in pl.net_sinks[n]:
            feed = (k[0]-1, y0, k[2])
            if feed not in comp:
                bad.append((k[0], k[2]))
        old_vox = wires | reps
        old_comp_size = len({v for v in old_vox if v in comp})
        if bad:
            still_bad.append((n, len(pl.net_sinks[n]), bad, len(nodes), len(comp)))
        else:
            fixed.append((n, len(nodes), len(comp)))
    print(f"=== connectivity with the FULL structure (dust+rep+torch+support) ===")
    print(f"nets fully fed: {len(fixed)}/{len(nets)}")
    print(f"nets still failing: {len(still_bad)}")
    for (n, ns, bad, nn, nc) in still_bad[:14]:
        print(f"  {n:5s} {len(bad)}/{ns} bad  nodes={nn:4d} comp={nc:4d}  "
              f"sinks={bad[:3]}")
    occ = {}
    for nn2, ws in res.wires.items():
        for p in ws:
            occ[p] = nn2
    for nn2, reps2 in res.repeaters.items():
        for (q, _f) in reps2:
            occ[q] = nn2
    for p in res.torches:
        occ[p] = tn.get(p, "?")
    for (q, _b) in res.wall_torches:
        occ[q] = wn.get(q, "?")
    print(f"\ninterfering pairs (measured): {coupling.count_shorts(occ)}")
    print(f"router-reported failed: {len(res.failed)}")


if __name__ == "__main__":
    main()
