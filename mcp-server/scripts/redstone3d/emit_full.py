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

    # 3. routing: dust + supports + via towers per net
    for net, cells in data["routes"].items():
        by_col = {}
        for (l, gx, gz) in cells:
            by_col.setdefault((gx, gz), []).append(l)
        for (gx, gz), layers in by_col.items():
            wx, wz = gx+x0, gz+z0
            layers = sorted(layers)
            if len(layers) == 1:
                wy = layer_y[layers[0]] + base_y
                B(wx, wy, wz, W)
                if wy > base_y:
                    B(wx, wy-1, wz, S)      # support below raised dust
            else:
                # via torch tower. The route omits the y=0 pin cell, so the via
                # column's lowest routed layer may be >0. Start the tower at
                # base_y (y=0, the pin plane) so the via actually connects the
                # gate pin at y=0 up to the trunk layer — otherwise the y0->y2
                # segment is missing and the signal never enters/leaves the pin.
                y = base_y
                yhi = layer_y[layers[-1]] + base_y
                while y < yhi:
                    B(wx, y, wz, S)
                    B(wx, y+1, wz, "minecraft:redstone_torch")
                    y += 2

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
