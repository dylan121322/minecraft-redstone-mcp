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

## Fully-Automatic Routing (PathFinder negotiated congestion)

Modules are **automatically routed** — no manual wiring — using PathFinder-style
negotiated-congestion routing (`maze_router.route_negotiated`), offloaded to a
32-thread Windows box for the compute-heavy iterations.

### Auto-routed module results (all LEGAL, shared=0)

| Module        | Gates | Wires  | Iters | Time  | Status |
|---------------|-------|--------|-------|-------|--------|
| Control       | 22    | 803    | 84    | 47s   | LEGAL ✅ |
| Mux_2to1      | 25    | 1155   | 67    | 62s   | LEGAL ✅ |
| ALU_Control   | 31    | 1799   | 68    | 131s  | LEGAL ✅ |
| Imm_Gen       | 32    | 2210   | 63    | 189s  | LEGAL ✅ |
| Forwarding    | 92    | 13803  | 49    | 146s  | LEGAL ✅ (portfolio) |
| ALU           | 197   | —      | —     | —     | hard case (see below) |

Each produces a fully-wired `.litematic` (cells + routed redstone + repeaters)
ready for direct in-game paste via Litematica — no manual wiring.

### Routing algorithm

- **`route_negotiated`** — serial PathFinder: every net reroutes against a
  present-cost + history-cost field; congested voxels get pricier each iteration
  until routing is legal (zero shared voxels). Converges reliably for ≤90 gates.
- **`route_solve.py` (portfolio)** — for dense modules, runs N parallel variants
  with escalating history-increment `{1,2,4}` × spacings `{10,16,24}` × seeds;
  first variant to legalize wins. Saturates all cores AND guarantees convergence
  (Forwarding legalized via `hist_inc=4.0` in 49 iters).
- **A\* corridor bounding** — each net's search is bounded to its bounding-box +
  margin with a Manhattan heuristic, keeping per-net routing fast on large chips.

### Windows compute offload

yosys synthesis runs on the Mac (fast); the heavy routing runs on Windows
(9950X3D, 32 threads). Netlists ship as JSON; `route_solve.py` / `batch_route.py`
run the portfolio there. `route_job.py` handles single-module jobs.

### Known hard case: ALU (197 gates)

The 8-bit ALU has 2× Forwarding's gate count with dense interconnect. Even the
16-variant portfolio (600 iters each, ~3.5 CPU-hours) did not legalize it —
the placement is too congested for the router to find non-shorting paths.
**Fix path**: improve placement (wider dedicated routing channels, or split the
ALU into per-bit slices routed independently then composed). Logic is verified
(80/80); only physical routing at this density remains.

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
