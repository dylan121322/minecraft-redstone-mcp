# RISC-V → Minecraft redstone build — session status

Goal: build each ALU-level module (Control, Mux_2to1, ALU_Control, Imm_Gen,
Forwarding, ALU) standalone in-game on frp-tag.com:40269 and verify usability.
NOT assembling them into a CPU — each module is a standalone component.

## Verified this session
- 6 gate cells build + pass truth tables in-game (NOT/BUF 2/2, AND/OR/NAND/NOR 4/4).
- Physics on vanilla /setblock (no block updates): see memory redstone-setblock-physics.
  Reliable primitives: dust-driven inputs, repeater-via layer change, up-over-down
  bridge (verified 4/4 in test_via.cjs). Repeater facing = REVERSE of flow.
- Old maze_router "LEGAL" is a false pass (ignores adjacency shorts + floating dust):
  see memory riscv-redstone-router-bug. Measured 1292 shorts + 833 floats on alu1.

## New router: route_buildable.py (2-layer directional)
- FLAT routing WORKS: NOT→NOT, AND, fanout all pass MCHPRS 0 shorts/0 floats.
- BRIDGE integration is the remaining hard part (alu1 → 10/40, bridges short + outputs stuck).
- 3 parallel agents attacking: (A) bridge gadget correctness, (B) multi-bridge
  isolation rules, (C) trunk-and-branch for high-fanout PI/op nets.

## Validation ladder
L1 MCHPRS (local, fast, catches shorts as wrong outputs) → L2 in-game alu1 →
L3 Control/Mux/ALU_Control/Imm_Gen in-game → L4 Forwarding/ALU.

## Key files (scripts/riscv_build/)
- export_blocks.py — synth → flat block-list JSON
- build_verify.cjs — bot builds JSON + drives PI blocks + reads output lamps/power
- verify_module_mchprs.py — L1: route alu1 + MCHPRS truth table
- measure_2d.py — planar routability probe
- test_*.cjs — in-game physics probes (crossover, via, climb, activation)
- AGENT_A/B/C_*.py — parallel bridge subtask outputs (in progress)
scripts/redstone3d/: route_buildable.py, build_from_route.py, verify_buildable.py
