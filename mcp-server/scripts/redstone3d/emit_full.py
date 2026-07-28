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
TORCH = "minecraft:redstone_torch"


def trunk_plane_y(base_y, layer):
    """World-Y of the trunk DUST plane for a given (even) trunk layer. A source
    torch tower of n=layer torches puts its top dust at base_y+2*layer+1, so the
    whole net's trunk dust lives on that ODD plane (supports at even Y below).
    Verified in test_rise_aligned.py (layers 2..20 all non-inverting)."""
    return base_y + 2 * layer + 1


def _emit_rise(B, wx, wz, base_y, layer):
    """Non-inverting 1x1 source RISE to trunk_plane_y(base_y,layer). layer MUST
    be even (router even_layers_only) so torch count is even => non-inverting.
    Caller drives a repeater feed from the WEST at (wx-1, base_y). Returns the
    top dust Y (== trunk_plane_y). Verified: test_rise_aligned.py."""
    B(wx - 1, base_y, wz, rep(FLOW_FACING[(1, 0)]))   # repeater faces west, drives east
    B(wx, base_y, wz, S)                              # block0
    y = base_y
    for _ in range(layer):
        B(wx, y + 1, wz, TORCH)                       # standing torch (inverts)
        B(wx, y + 2, wz, S)                           # block on top
        y += 2
    top_y = y + 1
    B(wx, top_y, wz, W)                               # trunk dust on final block
    return top_y


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

    # 3. routing per net. Signal flow: source pin (y0, driven by a gate output)
    #    -> RISE (1x1 vertical torch tower, verified non-inverting/no-decay) to
    #    the net's trunk layer -> flat trunk run -> DROP (+x staircase, verified)
    #    down to each sink pin (y0, feeds a gate input).
    #    Source vs sink is taken from the PLACEMENT (net_sources / net_sinks),
    #    not guessed from cell layers, so direction is always correct.
    from collections import Counter
    from via_gadget import drop_cells_west
    for net, cells in data["routes"].items():
        layer_count = Counter(l for (l, gx, gz) in cells)
        trunk_layer = layer_count.most_common(1)[0][0]
        # trunk DUST plane at odd Y = base_y + 2*trunk_layer + 1 (see
        # trunk_plane_y / test_rise_aligned). Supports one below.
        trunk_wy = trunk_plane_y(base_y, trunk_layer)

        # 3a. flat trunk run: lay every trunk-layer cell as dust on the odd
        #     plane, support below. This is the abstract router's connected path.
        trunk_cols = set()
        for (l, gx, gz) in cells:
            if l != trunk_layer:
                continue
            wx, wz = gx + x0, gz + z0
            trunk_cols.add((wx, wz))
            B(wx, trunk_wy, wz, W)
            B(wx, trunk_wy - 1, wz, S)

        # 3b. SOURCE rise: even-layer torch tower from the driver pin (y0) up to
        #     the trunk plane. Top dust lands at (swx, trunk_wy, swz) and joins
        #     the trunk run there (the abstract via guarantees this column is a
        #     trunk cell). Feed is a repeater the tower places to the pin's west.
        src = placement.net_sources.get(net)
        if src is not None and trunk_layer > 0:
            swx, swz = src[0], src[2]
            ty = _emit_rise(B, swx, swz, base_y, trunk_layer)
            # ensure join: trunk dust at the source column
            B(swx, ty, swz, W)
            if (swx, swz) not in trunk_cols:
                B(swx, ty - 1, swz, S)
        elif src is not None:
            B(src[0], base_y, src[2], W)

        # 3c. SINK drops: +x staircase from trunk_wy down to each sink pin y0.
        #     drop_cells starts at (x, trunk_wy) trunk dust and lands y0 at x_out;
        #     we want the landing to be the pin's WEST feed at (px-1, pz). So the
        #     drop must START far enough WEST that it lands at px-1. But the trunk
        #     dust for this net sits at the sink's own column (kgx,kgz) on the
        #     trunk layer (the abstract via cell). Emit the staircase from there.
        for k in placement.net_sinks.get(net, []):
            kwx, kwz = k[0], k[2]
            if trunk_layer > 0:
                # ensure a trunk dust exists at the sink column to launch the drop
                B(kwx, trunk_wy, kwz, W)
                if (kwx, kwz) not in trunk_cols:
                    B(kwx, trunk_wy - 1, kwz, S)
                # -x staircase: descend WEST of the sink column so the landing is
                # WEST of the input repeater at kwx (never overwrites the pin).
                pr, xo = drop_cells_west(kwx, kwz, trunk_wy, base_y)
                for (dx_, dy_, dz_, blk) in pr:
                    B(dx_, dy_, dz_, blk)
                # landing at (xo, base_y) is west of kwx. Bridge east to the pin's
                # west feed at (kwx-1) — all cells stay < kwx, so the repeater at
                # (kwx) reads a driven west neighbour and is never covered.
                for bx in range(xo, kwx):        # xo .. kwx-1 inclusive
                    B(bx, base_y, kwz, W)
            else:
                B(kwx - 1, base_y, kwz, W)

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
