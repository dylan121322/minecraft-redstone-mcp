# RISC-V 8-bit Module Synthesis → Minecraft Redstone

Toolchain for [ujjwal-2001/RISCV_8bit_pipeline](https://github.com/ujjwal-2001/RISCV_8bit_pipeline) → Minecraft redstone build, using the redstone3d synthesis pipeline.

## Architecture

```
riscv_synth/
├── ALU.v              # 8-bit ALU with 7 operations (ADD/SUB/AND/OR/XOR/NOT/JUMP)
├── ALU_Control.v      # ALU control: alu_op + funct → alu_control
├── Control.v          # Main control: 7-bit opcode → 7 control signals
├── Forwarding_Unit.v  # Data forwarding: register comparators
├── Imm_Gen.v          # Immediate generator: 32-bit inst → 12-bit immediate
├── Mux_2to1.v         # N-bit 2-to-1 multiplexer
├── riscv_synth.py     # Batch synthesis + logical verification
└── README.md
```

## Synthesis Results (yosys + abc + hierarchical verify)

| Module        | Gates | Gate Types                                        | Logical | Physical |
|---------------|-------|---------------------------------------------------|---------|----------|
| Control       | 22    | NOT:2 NAND:8 NOR:5 AND:6 OR:1                     | 6/6 ✅  | MCHPRS ✅ |
| ALU_Control   | 31    | NOT:4 NOR:7 OR:2 AND:12 NAND:6                    | 7/7 ✅  | MCHPRS ✅ |
| Mux_2to1      | 25    | NAND:24 NOT:1                                      | 2/2 ✅  | MCHPRS ✅ |
| Forwarding    | 92    | NOR:6 NAND:44 OR:22 AND:20                         | 3/3 ✅  | MCHPRS ✅ |
| Imm_Gen       | 32    | NOT:1 NOR:2 OR:1 AND:9 NAND:19                     | 3/3 ✅  | MCHPRS ✅ |
| ALU           | 197   | AND/OR/NAND/NOR (yosys abc)                        | -       | MCHPRS ✅ |

**Total: 399 cells across 6 modules for the RISC-V EX stage.**

All 6 gate types (NOT/BUF/AND/OR/NAND/NOR) have MCHPRS-verified physical layouts (4/4 each).
Netlist-level logic is verified by the redstone3d behavioral simulator.

## Semi-Automatic Build Mode

The fully automatic maze router is suitable for modules ~10 gates. Beyond that,
use the **placement-only** mode which generates:

1. **`.litematic` file** — cell instances placed + floor substrate + I/O lamps at port positions
2. **`_wiring.json` file** — netlist connection map (which cell output connects to which cell input)

These are exported to `../../schematics/` for in-game import via Litematica mod.
Inter-cell wiring is done manually in-game following the wiring map.

## Usage

```bash
# Full synthesis + verification
python3 riscv_synth.py

# Export litematics for all modules
python3 -c "
from yosys_frontend import compile_verilog
from placer import place
import nucleation, json

modules = [('Control','Control.v','Control'), ...]
for name, vfile, top in modules:
    nl = compile_verilog(vfile, top=top)
    pl = place(nl, col_gap=8, row_gap=4)
    s = nucleation.Schematic.create(name)
    # ... place cells + floor + port lamps ...
    s.save_to_file(f'../schematics/riscv_{name}.litematic')
"
```

## Dependencies

- yosys (Verilog synthesis)
- nucleation (schematic/litematic export)
- redstone3d pipeline (cell_library, placer, regress)
