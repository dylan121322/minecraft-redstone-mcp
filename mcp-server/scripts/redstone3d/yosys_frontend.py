"""
yosys_frontend.py — Verilog → (yosys synth + abc map) → our netlist dict.

Uses industrial logic synthesis to optimize gate count and fan-out before
place & route. yosys+abc reduces e.g. a full adder from 19 hand-expanded NAND
gates to 7 (3 NAND + 2 OR + 2 AND), all mapped to cells we have.

Flow:
  read_verilog → synth -flatten → abc -g AND,OR,NAND,NOR → write_json
  then parse the JSON into {cells, inputs, outputs} for placer/maze_router.

yosys gate types map to our cell library:
  $_NOT_ → NOT, $_AND_ → AND, $_OR_ → OR, $_NAND_ → NAND, $_NOR_ → NOR
  $_BUF_ → BUF
"""
from __future__ import annotations
import json
import os
import subprocess
import tempfile
from typing import Dict, List, Tuple

GATE_MAP = {
    "$_NOT_": ("NOT", ["A"]),
    "$_BUF_": ("BUF", ["A"]),
    "$_AND_": ("AND", ["A", "B"]),
    "$_OR_":  ("OR", ["A", "B"]),
    "$_NAND_": ("NAND", ["A", "B"]),
    "$_NOR_": ("NOR", ["A", "B"]),
}

# abc -g gate set restricted to what we can place. NOT/BUF handled by yosys.
ABC_GATES = "AND,OR,NAND,NOR"


def synthesize_verilog(verilog_path: str, top: str = None,
                       abc_gates: str = ABC_GATES) -> dict:
    """Run yosys+abc, return the parsed JSON netlist dict."""
    out_json = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
    top_arg = f"-top {top}" if top else ""
    script = (
        f"read_verilog {verilog_path}; "
        f"synth -flatten {top_arg}; "
        f"abc -g {abc_gates}; "
        f"opt_clean; "
        f"write_json {out_json}"
    )
    res = subprocess.run(["yosys", "-p", script],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yosys failed:\n{res.stderr[-2000:]}")
    with open(out_json) as f:
        data = json.load(f)
    os.unlink(out_json)
    return data


def to_netlist(yosys_json: dict, module: str = None) -> dict:
    """Convert yosys JSON to our netlist dict {cells, inputs, outputs}.

    Nets are yosys 'bits' (integers, or 'x'/'0'/'1' constants). We name each
    net "n<bit>". Constant bits become tie cells.
    """
    modules = yosys_json["modules"]
    if module is None:
        module = next(iter(modules))
    m = modules[module]

    def net_name(bit):
        if isinstance(bit, str):
            return f"const_{bit}"      # '0','1','x','z'
        return f"n{bit}"

    cells: Dict[str, dict] = {}
    inputs: List[str] = []
    outputs: List[str] = []

    # ports
    for pname, pd in m["ports"].items():
        bits = pd["bits"]
        for i, bit in enumerate(bits):
            nn = net_name(bit)
            label = pname if len(bits) == 1 else f"{pname}[{i}]"
            if pd["direction"] == "input":
                inputs.append(nn)
            elif pd["direction"] == "output":
                outputs.append(nn)

    # cells
    for cname, cd in m["cells"].items():
        ctype = cd["type"]
        if ctype not in GATE_MAP:
            raise ValueError(f"unmapped gate type {ctype!r} in {cname}; "
                             f"extend GATE_MAP / abc gate set")
        gtype, in_pins = GATE_MAP[ctype]
        conns = cd["connections"]
        ins = {}
        outs = {}
        for pin in in_pins:
            bit = conns[pin][0]
            ins[pin] = net_name(bit)
        # output pin is Y in yosys gate prims -> our Q
        ybit = conns["Y"][0]
        outs["Q"] = net_name(ybit)
        # clean name (strip yosys mangling)
        clean = cname.split("$")[-1].replace(":", "_").replace(".", "_")[:24] or cname
        clean = f"g{len(cells)}_{gtype}"
        cells[clean] = {"type": gtype, "inputs": ins, "outputs": outs}

    # dedupe port net lists preserving order
    inputs = list(dict.fromkeys(inputs))
    outputs = list(dict.fromkeys(outputs))
    return {"cells": cells, "inputs": inputs, "outputs": outputs,
            "port_bits": {p: pd["bits"] for p, pd in m["ports"].items()},
            "module": module}


def compile_verilog(verilog_path: str, top: str = None) -> dict:
    return to_netlist(synthesize_verilog(verilog_path, top))


if __name__ == "__main__":
    import sys
    v = sys.argv[1] if len(sys.argv) > 1 else "_fa.v"
    nl = compile_verilog(v)
    from collections import Counter
    print(f"module: {nl['module']}")
    print(f"cells: {len(nl['cells'])}  ({dict(Counter(c['type'] for c in nl['cells'].values()))})")
    print(f"inputs: {nl['inputs']}")
    print(f"outputs: {nl['outputs']}")
    for cn, cd in nl["cells"].items():
        print(f"  {cn}: {cd['type']} in={cd['inputs']} out={cd['outputs']}")
