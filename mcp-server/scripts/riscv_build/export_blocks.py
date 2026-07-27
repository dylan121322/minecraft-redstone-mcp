"""
export_blocks.py — Export a synthesized module (or a single cell) as a flat
list of (x,y,z,blockstate) placements + PI/PO metadata, as JSON, so the bot
can build it with /setblock and drive/read it in-game.

We reuse the SAME synth pipeline (place + route + build_fn) that MCHPRS verifies,
but instead of handing the schematic to MCHPRS we serialize every block.

Primary inputs are emitted as their injection position (west of PI) — the bot
places redstone_block/air there per test vector. PI net position itself is a
wire. Output probe = primary output position.

Usage:
  python3 export_blocks.py <module>          # Control|ALU_Control|Mux_2to1|Imm_Gen|Forwarding|alu1
  python3 export_blocks.py cell NOT          # a single library cell
"""
from __future__ import annotations
import sys, os, json

HERE = os.path.dirname(os.path.abspath(__file__))
R3D = os.path.join(HERE, "..", "redstone3d")
RSV = os.path.join(HERE, "..", "riscv_synth")
sys.path.insert(0, R3D)
sys.path.insert(0, RSV)

import nucleation as nuc  # noqa


class Recorder:
    """Quacks like nuc.Schematic for the build_fn, but records placements."""
    def __init__(self):
        self.blocks = {}  # (x,y,z) -> blockstate string (last write wins)

    def set_block_from_string(self, x, y, z, s):
        if s == "minecraft:air":
            self.blocks.pop((int(x), int(y), int(z)), None)
        else:
            self.blocks[(int(x), int(y), int(z))] = s

    def fill_cuboid(self, x0, y0, z0, x1, y1, z1, s):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            for y in range(min(y0, y1), max(y0, y1) + 1):
                for z in range(min(z0, z1), max(z0, z1) + 1):
                    self.set_block_from_string(x, y, z, s)


def export_cell(gtype: str) -> dict:
    import cell_library as clib
    cell = clib.get(gtype)
    rec = Recorder()
    ox = oy = oz = 0
    # floor under the cell + input stubs
    for dx in range(-3, cell.width + 2):
        for dz in range(-1, cell.depth + 1):
            rec.set_block_from_string(ox + dx, oy - 1, oz + dz, "minecraft:stone")
    cell.emit(rec, ox, oy, oz)

    # PI injection = one block west of each input pin; PI pin itself already a
    # repeater/wire from the cell. We feed a wire between injector and pin.
    inj = {}
    for name, (lx, ly, lz) in cell.inputs.items():
        # injector sits 2 west, wire at 1 west so a dust drives the pin
        rec.set_block_from_string(ox + lx - 1, oy + ly, oz + lz, "minecraft:redstone_wire")
        rec.set_block_from_string(ox + lx - 2, oy + ly - 1, oz + lz, "minecraft:stone")
        inj[name] = [ox + lx - 2, oy + ly, oz + lz]

    outs = {name: [ox + lx, oy + ly, oz + lz] for name, (lx, ly, lz) in cell.outputs.items()}
    return {
        "name": f"cell_{gtype}",
        "blocks": [[x, y, z, s] for (x, y, z), s in rec.blocks.items()],
        "inputs": inj,           # name -> [x,y,z] where redstone_block goes for '1'
        "outputs": outs,         # name -> [x,y,z] output wire to read power
        "input_bits": list(cell.inputs.keys()),
        "kind": "cell",
    }


def export_module(module: str) -> dict:
    from yosys_frontend import compile_verilog
    from synth import synthesize

    MODS = {
        "Control": ("Control.v", "Control"),
        "ALU_Control": ("ALU_Control.v", "ALU_Control"),
        "Mux_2to1": ("Mux_2to1.v", "Mux_2to1"),
        "Imm_Gen": ("Imm_Gen.v", "Imm_Gen"),
        "Forwarding_Unit": ("Forwarding_Unit.v", "Forwarding_Unit"),
        "alu1": ("alu1.v", "alu1"),
    }
    vfile, top = MODS[module]
    nl = compile_verilog(os.path.join(RSV, vfile), top=top)
    pl, route, build_fn = synthesize(nl)

    rec = Recorder()
    # build with all-zero inputs (structure is input-independent; PI blocks set later by bot)
    zero = {k: 0 for k in nl["inputs"]}
    build_fn(rec, zero)

    # PI injection positions = one west of each PI pos (synth places redstone_block there)
    inj = {net: [pos[0] - 1, pos[1], pos[2]] for net, pos in pl.primary_inputs.items()}
    outs = {net: list(pos) for net, pos in pl.primary_outputs.items()}

    return {
        "name": module,
        "blocks": [[x, y, z, s] for (x, y, z), s in rec.blocks.items()],
        "inputs": inj,
        "outputs": outs,
        "input_bits": list(nl["inputs"]),
        "output_bits": list(nl["outputs"]),
        "gates": len(nl["cells"]),
        "kind": "module",
    }


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "cell":
        data = export_cell(sys.argv[2])
    else:
        data = export_module(sys.argv[1])
    out = os.path.join(HERE, f"{data['name']}.blocks.json")
    with open(out, "w") as f:
        json.dump(data, f)
    bb = data["blocks"]
    xs = [b[0] for b in bb]; ys = [b[1] for b in bb]; zs = [b[2] for b in bb]
    print(f"exported {data['name']}: {len(bb)} blocks, "
          f"bbox x[{min(xs)},{max(xs)}] y[{min(ys)},{max(ys)}] z[{min(zs)},{max(zs)}]")
    print(f"  inputs={list(data['inputs'])[:6]}{'...' if len(data['inputs'])>6 else ''}")
    print(f"  outputs={list(data['outputs'])[:6]}{'...' if len(data['outputs'])>6 else ''}")
    print(f"  -> {out}")
