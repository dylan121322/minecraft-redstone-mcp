"""
diag_y_chain.py — cout is 30/40 and MOVES; y is 20/40 and STUCK at 1. So the
adder path works and the y path does not: y's driving gate must see a floating
input, which pins its output torch on.

Walk backwards from the y output net through the netlist, and for every net in
its cone report whether the router fed it (connected, per the full-structure
walk) — the first unfed net in the cone is what pins y.
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling

ORTH, DIAG = coupling.ORTH, coupling.DIAG
H4 = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))


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


def net_component(res, pl, n):
    wires = set(res.wires.get(n, ()))
    reps = {p for (p, _f) in res.repeaters.get(n, ())}
    torch = {p for p in res.torches if res.torch_nets.get(p) == n}
    wt = {p for (p, _b) in res.wall_torches if res.wall_torch_nets.get(p) == n}
    mine = wires | reps | torch | wt
    cols = {(p[0], p[2]) for p in mine}
    sup = {s for s in res.supports if (s[0], s[2]) in cols}
    vox = mine | sup
    src = pl.net_sources.get(n)
    if src is None or not vox:
        return set(), vox
    seed = [v for v in vox
            if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
    comp = set(seed); dq = deque(seed)
    while dq:
        cur = dq.popleft()
        cand = [(cur[0]+d[0], cur[1]+d[1], cur[2]+d[2]) for d in H4]
        cand += [(cur[0], cur[1]+1, cur[2]), (cur[0], cur[1]-1, cur[2])]
        for d in H4:
            cand.append((cur[0]+d[0], cur[1]+1, cur[2]+d[2]))
            cand.append((cur[0]+d[0], cur[1]-1, cur[2]+d[2]))
        for q in cand:
            if q in vox and q not in comp:
                comp.add(q); dq.append(q)
    return comp, vox


def main():
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n8").split("+"))
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

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    y_net = nm(pb["y"][0]); c_net = nm(pb["cout"][0])
    print(f"y net = {y_net}   cout net = {c_net}")

    # driver map: net -> (cell, gate type, its input nets)
    drv = {}
    for cname, cd in nl["cells"].items():
        for pin, net in cd.get("outputs", {}).items():
            drv[net] = (cname, cd["type"], list(cd.get("inputs", {}).values()))

    y0 = pl.bounds[0][1]
    seen = set()
    stack = [(y_net, 0)]
    print(f"\ncone of {y_net} (net: gate, fed?, unfed sinks):")
    while stack:
        net, depth = stack.pop()
        if net in seen or depth > 8:
            continue
        seen.add(net)
        cell = drv.get(net)
        if net not in pl.net_sinks:
            status = "PRIMARY INPUT" if net in pl.primary_inputs else "no sinks"
            print(f"{'  '*depth}{net}: {status}")
        else:
            comp, vox = net_component(res, pl, net)
            bad = [(k[0], k[2]) for k in pl.net_sinks[net]
                   if (k[0]-1, y0, k[2]) not in comp]
            tag = "OK" if not bad else f"UNFED {bad[:3]}"
            gt = cell[1] if cell else "?"
            print(f"{'  '*depth}{net}: {gt:5s} vox={len(vox):4d} comp={len(comp):4d} {tag}")
        if cell:
            for src_net in cell[2]:
                stack.append((src_net, depth + 1))


if __name__ == "__main__":
    main()
