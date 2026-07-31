"""
diag_global_link.py — walk one global net's chain in the built world and print the
power at each stage, so the break point is a fact rather than a guess.

Stages: source pin -> driving repeater -> up-tower rungs -> tower top dust ->
leg along the tower column to the trunk row -> the trunk row itself -> the sink's
column leg -> parity bridge -> down-tower rungs -> the sink feed cell.
"""
import sys, os, json
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); sys.path.insert(0, os.path.join(BASE, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_global_first import route_adaptive

RB = "minecraft:redstone_block"; W = "minecraft:redstone_wire"


def main():
    nls = json.load(open(os.path.join(BASE, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    which = sys.argv[2] if len(sys.argv) > 2 else None
    pl = place(nls[mod], col_gap=16, row_gap=16)
    rep, r, g, zres = route_adaptive(pl)
    net = which or g.routed[0]
    src = pl.net_sources[net]; sinks = pl.net_sinks[net]
    row = g.trunk_rows[net]
    ty = r.trunk_y
    sx, sz = src[0], src[2]
    print(f"{mod} {net}: src={(sx, sz)} sinks={[(k[0], k[2]) for k in sinks]} "
          f"row={row} trunk_y={ty}")

    # build: floor + cells + this net's global geometry only
    blocks = {}
    def st(x, y, z, s):
        if s == "minecraft:air":
            blocks.pop((x, y, z), None)
        else:
            blocks[(x, y, z)] = s
    mn, mx = pl.bounds
    for x in range(mn[0] - 2, mx[0] + 3):
        for z in range(mn[2] - 2, row + 4):
            st(x, r.base_y - 1, z, "minecraft:stone")
    class A:
        def set_block_from_string(self, x, y, z, s): st(int(x), int(y), int(z), s)
    for pc in pl.placed.values():
        pc.cell.emit(A(), *pc.origin)
    for (x, y, z), b in g.blocks.items():
        st(x, y, z, b)

    sc = nuc.Schematic.create("dgl")
    for (x, y, z), s in blocks.items():
        if "wall_torch" in s and y == r.base_y:
            continue
        sc.set_block_from_string(x, y, z, s)
    sc.set_block_from_string(sx - 1, r.base_y, sz, RB)
    sc.set_block_from_string(sx, r.base_y, sz, W)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(120)

    def show(label, pos):
        b = blocks.get(pos, "-")
        print(f"  {label:26s} {pos} [{b.replace('minecraft:', '')[:26]:26s}] "
              f"pow={w.get_redstone_power(*pos)}")

    show("source pin", (sx, r.base_y, sz))
    show("drive repeater", (sx + 1, r.base_y, sz))
    tcol = sx + 2
    for y in range(r.base_y, ty + 1):
        p = (tcol, y, sz)
        if p in blocks:
            show(f"tower y={y}", p)
    # leg along tower column toward the row
    step = 1 if row > sz else -1
    for z in range(sz, row + step, step * max(1, abs(row - sz) // 6 or 1)):
        p = (tcol, ty, z)
        if p in blocks:
            show(f"leg z={z}", p)
    show("leg end at row", (tcol, ty, row))
    # sample the trunk row
    for k in sinks:
        fx = k[0] - 9   # shaft column (see route_global_first: k-9)
        for x in range(min(tcol, fx), max(tcol, fx) + 1,
                       max(1, abs(fx - tcol) // 6 or 1)):
            p = (x, ty, row)
            if p in blocks:
                show(f"row x={x}", p)
        show("row at sink col", (fx, ty, row))
        # sink column leg
        for z in range(row, k[2] - step, -step * max(1, abs(row - k[2]) // 4 or 1)):
            p = (fx, ty, z)
            if p in blocks:
                show(f"sinkleg z={z}", p)
        for y in range(ty, r.base_y - 1, -1):
            p = (fx, y, k[2])
            if p in blocks:
                show(f"down y={y}", p)
        # walk the whole delivery run: tower bottom -> lead -> inverter -> feed
        for xx in range(fx, k[0] + 1):
            p = (xx, r.base_y, k[2])
            if p in blocks:
                show(f"deliver x={xx}", p)
        break


if __name__ == "__main__":
    main()
