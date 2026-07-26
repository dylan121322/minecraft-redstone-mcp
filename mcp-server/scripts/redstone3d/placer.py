"""
placer.py — 3D placement of gate cells from a netlist.

Strategy (layered / left-to-right dataflow):
  - X axis = logic depth (topological level). Signals flow west→east.
  - Each topo level occupies a COLUMN at a fixed x-range.
  - Within a column, cells stack along Z (side by side), separated by a
    routing gap so the router has room for wires.
  - Between columns, a routing channel (free x-range) lets nets travel east
    and fan across Z.
  - A voxel occupancy set records every block a cell will use, so the router
    can avoid collisions (NO_COORD_OVERLAP).

Input: a Module (from riscv_compiler) or a lightweight netlist dict:
  {
    "cells": {name: {"type": GATE, "inputs": {pin: net}, "outputs": {pin: net}}},
    "inputs": [net,...],   # module-level primary inputs
    "outputs": [net,...],  # module-level primary outputs
  }

Output: Placement with per-cell origin + absolute pin coords + occupancy.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Set, Optional
import cell_library as clib

Pos = Tuple[int, int, int]


@dataclass
class PlacedCell:
    name: str
    gtype: str
    cell: clib.Cell
    origin: Pos                      # absolute (x,y,z) of cell local (0,0,0)
    input_pins: Dict[str, Pos]       # pin name -> absolute pos
    output_pins: Dict[str, Pos]      # pin name -> absolute pos


@dataclass
class Placement:
    placed: Dict[str, PlacedCell]
    occupancy: Set[Pos]              # every voxel a cell occupies (y=0 and y=1)
    net_sources: Dict[str, Pos]      # net -> absolute pos of its driver output pin
    net_sinks: Dict[str, List[Pos]]  # net -> list of absolute input pin positions
    primary_inputs: Dict[str, Pos]   # module input net -> injection pos (west edge)
    primary_outputs: Dict[str, Pos]  # module output net -> read pos (east edge)
    bounds: Tuple[Pos, Pos]          # (min, max) absolute

    def stats(self) -> dict:
        mn, mx = self.bounds
        return {
            "cells": len(self.placed),
            "nets": len(self.net_sources),
            "occupied_voxels": len(self.occupancy),
            "dimensions": (mx[0]-mn[0]+1, mx[1]-mn[1]+1, mx[2]-mn[2]+1),
        }


def _topo_levels(cells: Dict[str, dict], input_nets: Set[str]) -> List[List[str]]:
    """Assign each cell a topological level = max input-driver level + 1."""
    # net -> driver cell
    driver = {}
    for cname, cdata in cells.items():
        for pin, net in cdata.get("outputs", {}).items():
            driver[net] = cname

    level: Dict[str, int] = {}
    visiting: Set[str] = set()

    def cell_level(cname: str) -> int:
        if cname in level:
            return level[cname]
        if cname in visiting:      # cycle (sequential feedback) — break at 0
            return 0
        visiting.add(cname)
        lv = 0
        for pin, net in cells[cname].get("inputs", {}).items():
            if net in input_nets:
                continue
            if net in driver:
                lv = max(lv, cell_level(driver[net]) + 1)
        visiting.discard(cname)
        level[cname] = lv
        return lv

    for cname in cells:
        cell_level(cname)

    max_lv = max(level.values(), default=0)
    levels: List[List[str]] = [[] for _ in range(max_lv + 1)]
    for cname, lv in sorted(level.items()):
        levels[lv].append(cname)
    return levels


def place(netlist: dict, origin: Pos = (0, 0, 0),
          col_gap: int = 6, row_gap: int = 2) -> Placement:
    """Place cells in topological columns.

    col_gap: free x-blocks between cell columns (routing channel width).
    row_gap: free z-blocks between stacked cells in a column.
    """
    cells = netlist["cells"]
    input_nets = set(netlist.get("inputs", []))
    output_nets = set(netlist.get("outputs", []))

    levels = _topo_levels(cells, input_nets)

    ox0, oy0, oz0 = origin
    placed: Dict[str, PlacedCell] = {}
    occupancy: Set[Pos] = set()
    net_sources: Dict[str, Pos] = {}
    net_sinks: Dict[str, List[Pos]] = {}

    cur_x = ox0 + 2  # leave room for primary-input injection at west
    for lv, names in enumerate(levels):
        col_width = 0
        cur_z = oz0
        for cname in names:
            cdata = cells[cname]
            gtype = cdata["type"]
            cell = clib.get(gtype)
            cx, cy, cz = cur_x, oy0, cur_z

            # register occupancy over the cell bbox (y=0 and y=1)
            for lx in range(cell.width):
                for lz in range(cell.depth):
                    for ly in range(cell.height):
                        occupancy.add((cx + lx, cy + ly, cz + lz))

            in_pins = {p: cell.input_abs(p, cx, cy, cz) for p in cell.inputs}
            out_pins = {p: cell.output_abs(p, cx, cy, cz) for p in cell.outputs}
            placed[cname] = PlacedCell(cname, gtype, cell, (cx, cy, cz), in_pins, out_pins)

            # nets
            for pin, net in cdata.get("outputs", {}).items():
                if pin in out_pins:
                    net_sources[net] = out_pins[pin]
            for pin, net in cdata.get("inputs", {}).items():
                if pin in in_pins:
                    net_sinks.setdefault(net, []).append(in_pins[pin])

            col_width = max(col_width, cell.width)
            cur_z += cell.depth + row_gap
        cur_x += col_width + col_gap

    # Primary inputs: injection positions on the west edge, one z-row each
    primary_inputs: Dict[str, Pos] = {}
    pi_z = oz0
    for net in netlist.get("inputs", []):
        primary_inputs[net] = (ox0, oy0, pi_z)
        net_sources[net] = (ox0, oy0, pi_z)  # PI drives the net
        pi_z += 2

    # Primary outputs: read positions on the east edge
    primary_outputs: Dict[str, Pos] = {}
    for net in netlist.get("outputs", []):
        if net in net_sources:
            primary_outputs[net] = net_sources[net]

    all_pos = list(occupancy) + list(primary_inputs.values())
    if all_pos:
        mn = (min(p[0] for p in all_pos), min(p[1] for p in all_pos), min(p[2] for p in all_pos))
        mx = (max(p[0] for p in all_pos), max(p[1] for p in all_pos), max(p[2] for p in all_pos))
    else:
        mn = mx = origin

    return Placement(placed, occupancy, net_sources, net_sinks,
                     primary_inputs, primary_outputs, (mn, mx))


if __name__ == "__main__":
    # Demo: place a 1-bit full adder netlist (XOR expanded to NANDs later;
    # here use AND/OR/NOT directly for a half-adder-ish structure).
    netlist = {
        "cells": {
            "and1": {"type": "AND", "inputs": {"A": "a", "B": "b"}, "outputs": {"Q": "c_out"}},
            "or1":  {"type": "OR",  "inputs": {"A": "a", "B": "b"}, "outputs": {"Q": "aorb"}},
            "nand1":{"type": "NAND","inputs": {"A": "a", "B": "b"}, "outputs": {"Q": "nab"}},
            "and2": {"type": "AND", "inputs": {"A": "aorb", "B": "nab"}, "outputs": {"Q": "sum"}},
        },
        "inputs": ["a", "b"],
        "outputs": ["sum", "c_out"],
    }
    pl = place(netlist)
    print("Placement stats:", pl.stats())
    print("\nTopological placement:")
    for name, pc in pl.placed.items():
        print(f"  {name:6} {pc.gtype:5} @ {pc.origin}  in={pc.input_pins}  out={pc.output_pins}")
    print("\nNet sources:", {k: v for k, v in pl.net_sources.items()})
    print("Net sinks:", {k: v for k, v in pl.net_sinks.items()})
    print("Primary inputs:", pl.primary_inputs)
    print("Primary outputs:", pl.primary_outputs)

    # Collision check
    print(f"\nOccupancy: {len(pl.occupancy)} voxels, no overlaps by construction.")
