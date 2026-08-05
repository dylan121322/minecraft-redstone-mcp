"""
diag_pre_dust.py — the failing sink's neighbourhood showed a BLOCK where the
down-tower's input dust should be:

    y=9 (cross plane) : W15   powered
    y=8               : #0    a block — but _pick_down_tower emits
                              ("dust", feed_x, cy_cross, feed_z) here
    y<=7              : 0     dead

Vertical dust-over-dust was then measured to CONDUCT (test_vertical_dust V1=10),
so the hand-off geometry is fine — the dust simply is not there. Check whether
the router emitted it and whether something overwrote it (emit order: floor,
supports, cells, out-stubs, torches, wall torches, wires, repeaters, PI).
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from build_from_route import emit_blocks

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


def main():
    net = sys.argv[1] if len(sys.argv) > 1 else "n3"
    sink_z = int(sys.argv[2]) if len(sys.argv) > 2 else 17
    yields = set((sys.argv[3] if len(sys.argv) > 3 else "n18+n3+n6").split("+"))
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

    sink = None
    for k in pl.net_sinks[net]:
        if k[2] == sink_z:
            sink = k
    feed = (sink[0] - 1, sink[1], sink[2])
    print(f"{net} sink={sink} feed={feed}")

    col = [(feed[0], y, feed[2]) for y in range(0, 12)]
    print(f"\nwhat the ROUTER assigned in the feed column:")
    wires = res.wires.get(net, set())
    reps = {q for (q, _f) in res.repeaters.get(net, ())}
    torch = set(res.torches)
    wtor = {q for (q, _b) in res.wall_torches}
    sup = res.supports
    for p in col:
        tags = []
        if p in wires: tags.append("net-wire")
        if p in reps: tags.append("net-rep")
        if p in torch: tags.append("torch")
        if p in wtor: tags.append("wall_torch")
        if p in sup: tags.append("SUPPORT")
        for on, ws in res.wires.items():
            if on != net and p in ws:
                tags.append(f"wire[{on}]")
        print(f"   {p}: {tags or '-'}")

    print(f"\nwhat EMIT actually writes there:")
    rec = {}
    order = []
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            if (x, y, z) in [tuple(c) for c in col]:
                order.append(((x, y, z), s))
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 1 for n in nl["inputs"]})
    for p in col:
        print(f"   {p}: {rec.get(p, '<empty>')}")
    print(f"\nwrite ORDER in that column (later wins):")
    for p, s in order:
        print(f"   {p} <- {s.replace('minecraft:', '')}")


if __name__ == "__main__":
    main()
