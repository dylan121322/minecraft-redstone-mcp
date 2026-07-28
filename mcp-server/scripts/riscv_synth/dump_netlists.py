"""
dump_netlists.py — synthesize every combinational RISC-V module with yosys and
write the {module_name: netlist} dict that the routers/emit expect as
riscv_synth/netlists.json. This product was previously only produced on Win;
this makes the Mac toolchain self-contained.
"""
import os, json, sys
from collections import Counter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "redstone3d"))
from yosys_frontend import compile_verilog

WORKDIR = os.path.dirname(os.path.abspath(__file__))

# (json_key, verilog_file, top_module)
MODULES = [
    ("alu1",       "alu1.v",            "alu1"),
    ("ALU",        "ALU.v",             "ALU"),
    ("Control",    "Control.v",         "Control"),
    ("ALU_Control","ALU_Control.v",     "ALU_Control"),
    ("Mux2to1",    "Mux_2to1.v",        "Mux_2to1"),
    ("ImmGen",     "Imm_Gen.v",         "Imm_Gen"),
    ("Forwarding", "Forwarding_Unit.v", "Forwarding_Unit"),
]

def main():
    out = {}
    for key, vfile, top in MODULES:
        path = os.path.join(WORKDIR, vfile)
        if not os.path.exists(path):
            print(f"  SKIP {key}: {vfile} missing", flush=True)
            continue
        nl = compile_verilog(path, top=top)
        ct = Counter(c["type"] for c in nl["cells"].values())
        print(f"  {key}: {len(nl['cells'])} gates {dict(ct)} "
              f"in={len(nl['inputs'])} out={len(nl['outputs'])}", flush=True)
        out[key] = nl
    dst = os.path.join(WORKDIR, "netlists.json")
    json.dump(out, open(dst, "w"))
    print(f"wrote {dst}: {len(out)} modules")

if __name__ == "__main__":
    main()
