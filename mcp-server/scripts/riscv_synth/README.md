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

### ALU solved via bit-slicing (was the hard case)

Monolithic 8-bit ALU (197 gates, dense) resisted routing — a 16-variant
portfolio (~3.5 CPU-hours) never legalized. **Solution: bit-slicing.**

`alu1.v` is a 1-bit ALU slice (24 gates — same size as Control/Mux, routes in
~3s). `alu8_sliced.v` instantiates 8 slices with a carry chain (bit0.cin =
is_sub for two's-complement subtract). `alu_slice_compose.py` routes ONE slice
then **stamps it 8×** along X — deterministic composition, no 197-gate global
route needed.

| Approach | Result |
|----------|--------|
| Monolithic 197-gate route | 3.5 CPU-hours, never legalized ❌ |
| 8× 1-bit slice + stamp | **4.8s, LEGAL, 88416-block litematic ✅** |

Logic equivalence proven exhaustively: `alu8_sliced` matches the monolithic ALU
truth table for all 256×256 inputs × 5 ops (0 fails, bit-parallel sim).

> Carry-chain and op-broadcast inter-slice wiring: slices are stamped with
> matching port rows so cout[i]↔cin[i+1] and op[3:0] align along X; the physical
> connector wires between adjacent slice ports are short (added at compose time).

## Bit-parallel logic simulation (`../redstone3d/sim_bitparallel.py`)

Fast "coarse" functional sim with **no GPU** (numpy only). Packs 64 test vectors
per uint64 lane; gates become numpy bitwise ops; one topological forward pass
evaluates 64×M vectors at once.

| Sim | Rate | 8-bit ALU exhaustive (per op, 65536 vecs) |
|-----|------|-------------------------------------------|
| scalar eval_netlist | 1,203 vec/s | ~55s |
| **bit-parallel numpy** | **~120,000 vec/s** | **~0.5s** |

100× speedup turns sampled verification into **exhaustive** verification. Precise
MCHPRS timing sim stays per-slice on CPU (small, fast).

> GPU note: the Windows box (RTX 5080, sm_120 Blackwell) runs Python 3.14, which
> has no torch/cupy wheels yet. numpy bit-parallel already meets the "fast coarse
> simulation" goal without GPU; revisit CUDA when 3.13/3.14 wheels ship.

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
