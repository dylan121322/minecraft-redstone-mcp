"""
emit_full.py — GpuRouter route -> COMPLETE redstone block set (cells + dust +
supports + via towers + repeaters + PI injectors + PO probes).

Output: a flat dict {(x,y,z): blockstate} + metadata (PI inject positions, PO
read positions), serialized to JSON for MCHPRS verify AND in-game build.

Coordinate model:
  cells (gate bodies + pins) live at y = base_y (layer 0), placed by cell_library
  at their world origin. Routing cells (layer,gx,gz) map to world:
    x = gx + x0, z = gz + z0, y = base_y + layer_y[layer]
  A pin column appearing on multiple layers is a VIA -> torch tower.
  Horizontal same-layer dust -> wire + support stone below (if raised).
  Repeater inserted every <=13 dust along a run to refresh.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
import cell_library as clib

S = "minecraft:stone"; W = "minecraft:redstone_wire"; RB = "minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"

FLOW_FACING = {(1, 0): "west", (-1, 0): "east", (0, 1): "north", (0, -1): "south"}
MAX_RUN = 13


class Recorder:
    """Collects set_block calls into a dict (last write wins)."""
    def __init__(self):
        self.blocks = {}
    def set_block_from_string(self, x, y, z, s):
        if s == "minecraft:air":
            self.blocks.pop((int(x), int(y), int(z)), None)
        else:
            self.blocks[(int(x), int(y), int(z))] = s
    def fill_cuboid(self, x0, y0, z0, x1, y1, z1, s):
        for x in range(min(x0,x1), max(x0,x1)+1):
            for y in range(min(y0,y1), max(y0,y1)+1):
                for z in range(min(z0,z1), max(z0,z1)+1):
                    self.set_block_from_string(x, y, z, s)


def build_full(data, netlist, placement):
    """Return (blocks dict, pi_inject dict, po_read dict)."""
    rec = Recorder()
    B = rec.set_block_from_string
    x0, z0, base_y = data["x0"], data["z0"], data["base_y"]
    layer_y = data["layer_y"]

    # 1. floor slab under the whole footprint
    all_x = [c[1]+x0 for cells in data["routes"].values() for c in cells]
    all_z = [c[2]+z0 for cells in data["routes"].values() for c in cells]
    for pc in placement.placed.values():
        all_x.append(pc.origin[0]); all_z.append(pc.origin[2])
    fx0, fx1 = min(all_x)-2, max(all_x)+8
    fz0, fz1 = min(all_z)-2, max(all_z)+4
    for x in range(fx0, fx1+1):
        for z in range(fz0, fz1+1):
            B(x, base_y-1, z, S)

    # 2. gate cells (at y=base_y)
    for name, pc in placement.placed.items():
        pc.cell.emit(rec, *pc.origin)

    # 3. routing per net: trunk (flat, at the net's trunk layer) + horizontal
    #    rise/drop vias (via_gadget, verified non-inverting w/ repeater refresh).
    from collections import Counter
    from via_gadget import rise_cells, drop_cells
    for net, cells in data["routes"].items():
        # trunk layer = the layer holding most of this net's cells
        layer_count = Counter(l for (l, gx, gz) in cells)
        trunk_layer = layer_count.most_common(1)[0][0]
        trunk_wy = layer_y[trunk_layer] + base_y
        # emit trunk-layer cells flat (dust + support)
        for (l, gx, gz) in cells:
            if l != trunk_layer:
                continue
            wx, wz = gx+x0, gz+z0
            B(wx, trunk_wy, wz, W)
            if trunk_wy > base_y:
                B(wx, trunk_wy-1, wz, S)
        # via columns: pin (x,z) that need to connect y0<->trunk. Identify from
        # cells that are NOT on the trunk layer (the abstract via segments) —
        # take their (gx,gz) as the pin columns needing a rise/drop.
        via_cols = set((gx, gz) for (l, gx, gz) in cells if l != trunk_layer)
        for (gx, gz) in via_cols:
            wx, wz = gx+x0, gz+z0
            # emit a horizontal rise from y0 at this column up to trunk_wy, then
            # connect its top to the trunk cell here. (rise spreads in +x; the
            # trunk dust at (wx,trunk_wy,wz) is the join point.)
            pr, xo = rise_cells(wx, wz, base_y, trunk_wy)
            for (rx, ry, rz, blk) in pr:
                B(rx, ry, rz, blk)
            # ensure the rise top dust connects to the trunk dust at (wx,...):
            # rise ends at (xo, trunk_wy); put trunk dust bridging xo..wx if gap
            lo, hi = min(xo, wx), max(xo, wx)
            for bx in range(lo, hi+1):
                B(bx, trunk_wy, wz, W)
                if trunk_wy > base_y:
                    B(bx, trunk_wy-1, wz, S)
            # y0 dust at the pin column feeds the gate pin
            B(wx, base_y, wz, W)

    # 4. PI injectors + PO probes
    pi_inject = {}
    for net in netlist["inputs"]:
        pos = placement.primary_inputs.get(net)
        if pos:
            pi_inject[net] = [pos[0]-1, pos[1], pos[2]]  # redstone_block goes here for '1'
    po_read = {}
    for net in netlist["outputs"]:
        pos = placement.primary_outputs.get(net)
        if pos:
            po_read[net] = list(pos)

    return rec.blocks, pi_inject, po_read


if __name__ == "__main__":
    import json
    from placer import place
    from yosys_frontend import compile_verilog
    from route_gpu import GpuRouter
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = GpuRouter(pl, nlayers=30, layer_y=tuple(range(0, 60, 2)))
    routes, nbad, net_idx = r.route_partitioned(zone_width=80, verbose=False)
    unr = getattr(r, "unrouted", [])
    print(f"[{mod}] route: shorts={nbad} unrouted={len(unr)}")
    data = {"x0": r.x0, "z0": r.z0, "base_y": r.base_y,
            "layer_y": list(r.layer_y),
            "routes": {list(net_idx.keys())[list(net_idx.values()).index(i)]: cells
                       for i, cells in routes.items()}}
    blocks, pi, po = build_full(data, nls[mod], pl)
    xs=[k[0] for k in blocks]; ys=[k[1] for k in blocks]; zs=[k[2] for k in blocks]
    print(f"[{mod}] FULL geometry: {len(blocks)} blocks, "
          f"bbox x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}] z[{min(zs)},{max(zs)}]")
    print(f"  PI: {len(pi)}  PO: {len(po)}")
    out = {"blocks": [[x,y,z,s] for (x,y,z),s in blocks.items()],
           "pi_inject": pi, "po_read": po, "module": mod}
    json.dump(out, open(rf"E:\project\{mod}_full.json", "w"))
    print(f"  saved E:\\project\\{mod}_full.json")
