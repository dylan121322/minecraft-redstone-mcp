"""diag_n14_deep.py — n14's feed is COMPLETELY free (0 orth, 0 diag blockers)
yet both its sinks fail. So the router's SEARCH is the failure, not the physics.
Trace the router's decision path for n14: what does it own, where does its
bridge attempt die, and what surrounds its source?"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from placer import place

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


def main():
    ys = set((sys.argv[1] if len(sys.argv) > 1 else "n3+n5").split("+"))
    install_measured()
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in ys]
        tail = [n for n in nets if n in ys]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched

    # instrument _bridge to trace n14
    orig_bridge = r._bridge
    def traced(net, goal_xz, placements, climbed):
        if net == "n14":
            print(f"  _bridge n14 -> {goal_xz}  climbed={net in climbed}")
        res = orig_bridge(net, goal_xz, placements, climbed)
        if net == "n14":
            print(f"    result: {'None' if res is None else len(res)}")
        return res
    r._bridge = traced

    res = r.route(verbose=False, max_rounds=5)
    src = pl.net_sources["n14"]
    print(f"n14: source={src} sinks={pl.net_sinks['n14']}")
    print(f"n14 in failed? {'n14' in res.failed}")
    print(f"n14 wires: {len(res.wires.get('n14', ()))}")
    print(f"n14 repeaters: {len(res.repeaters.get('n14', []))}")
    print(f"n14 bridges: {res.bridges.get('n14')}")
    # component from source
    wires = set(res.wires.get("n14", ()))
    reps = {p for (p, _f) in res.repeaters.get("n14", ())}
    torch = {p for p in res.torches if res.torch_nets.get(p) == "n14"}
    wt = {p for (p, _b) in res.wall_torches if res.wall_torch_nets.get(p) == "n14"}
    mine = wires | reps | torch | wt
    cols = {(p[0], p[2]) for p in mine}
    sup = {s for s in res.supports if (s[0], s[2]) in cols}
    vox = mine | sup
    seed = [v for v in vox
            if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
    comp = set(seed); dq = deque(seed)
    while dq:
        cur = dq.popleft()
        for d in CONN:
            q = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
            if q in vox and q not in comp:
                comp.add(q); dq.append(q)
    print(f"connected component from source: {len(comp)}/{len(vox)}")
    y0 = pl.bounds[0][1]
    for k in pl.net_sinks["n14"]:
        feed = (k[0]-1, y0, k[2])
        print(f"  sink {k} feed {feed} in comp? {feed in comp}")


if __name__ == "__main__":
    main()
