"""
fold_placer.py — first-principles placer: fold the topological chain into a
serpentine (S-shape) so physically adjacent logic layers sit CLOSE, cutting
average net length and widening the space any single net competes for.

The current placer puts each topo level in its own column: depth=12 => 12
columns x ~26 wide => 317-wide field, and a net from L0 to L11 travels the whole
width. Folding 3 levels per column gives 4 columns; within each column, levels
stack in z (S-shape: even columns top-down, odd columns bottom-up so the chain
continues). Adjacent levels now sit either in the same column (short z link) or
the next column (short x link).

This module provides a `fold(netlist, levels_per_col, ...)` placement and a
measurement of the resulting connection lengths vs the current one. It does NOT
touch the router — routing still runs on whatever Placement it gets.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riscv_synth"))
from placer import _topo_levels, Placement, PlacedCell, clib
from typing import Dict, List, Tuple, Set


def fold_place(netlist, levels_per_col=3, col_gap=16, row_gap=16):
    """Serpentine placement: group levels into columns of `levels_per_col`;
    within a column, stack the gates in z, alternating direction per column so
    the signal chain continues without long back-tracks."""
    cells = netlist["cells"]
    input_nets = set(netlist.get("inputs", []))
    levels = _topo_levels(cells, input_nets)
    ox0, oy0, oz0 = 0, 0, 0

    # group levels into columns
    ncols = (len(levels) + levels_per_col - 1) // levels_per_col
    col_levels = [[] for _ in range(ncols)]
    for lv, names in enumerate(levels):
        col_levels[lv // levels_per_col].append((lv, names))

    placed = {}
    occupancy = set()
    net_sources, net_sinks = {}, {}
    out_stubs = []
    cur_x = ox0 + 2 + col_gap

    for ci, group in enumerate(col_levels):
        # direction: even col top-down (z increasing), odd col bottom-up
        down = (ci % 2 == 0)
        rows = []
        for (lv, names) in group:
            for cname in names:
                rows.append((lv, cname))
        if not down:
            rows = rows[::-1]
        cur_z = oz0
        for (lv, cname) in rows:
            cdata = cells[cname]
            gtype = cdata["type"]
            cell = clib.get(gtype)
            cx, cy, cz = cur_x, oy0, cur_z
            for lx in range(cell.width):
                for lz in range(cell.depth):
                    for ly in range(cell.height):
                        occupancy.add((cx + lx, cy + ly, cz + lz))
            in_pins = {p: cell.input_abs(p, cx, cy, cz) for p in cell.inputs}
            out_pins = {p: cell.output_abs(p, cx, cy, cz) for p in cell.outputs}
            placed[cname] = PlacedCell(cname, gtype, cell, (cx, cy, cz),
                                       in_pins, out_pins)
            for pin, net in cdata.get("outputs", {}).items():
                if pin in out_pins:
                    op = out_pins[pin]
                    ex = (op[0] + 1, op[1], op[2])
                    net_sources[net] = ex
                    out_stubs.append((op, ex))
            for pin, net in cdata.get("inputs", {}).items():
                if pin in in_pins:
                    net_sinks.setdefault(net, []).append(in_pins[pin])
            cur_z += cell.depth + row_gap
        cur_x += col_gap + max(clib.get(cells[n]["type"]).width
                               for (_l, n) in rows)

    # primary inputs at z of consumers
    primary_inputs = {}
    used_z = set()
    def claim(want):
        z = want; s = 0
        while any(abs(z - u) < 4 for u in used_z):
            s += 1
            z = want + (s if s % 2 else -s) * 4
        used_z.add(z)
        return z
    def _consumer_z(net):
        return sum(p[2] for p in net_sinks.get(net, [])) / \
            max(1, len(net_sinks.get(net, [])))
    for net in sorted(netlist.get("inputs", []), key=_consumer_z):
        zs = sorted(p[2] for p in net_sinks.get(net, []))
        want = zs[len(zs)//2] if zs else oz0
        z = claim(want)
        primary_inputs[net] = (ox0, oy0, z)
        net_sources[net] = (ox0, oy0, z)

    primary_outputs = {}
    for net in netlist.get("outputs", []):
        if net in net_sources:
            primary_outputs[net] = net_sources[net]

    all_pos = list(occupancy) + list(primary_inputs.values())
    mn = (min(p[0] for p in all_pos), min(p[1] for p in all_pos),
          min(p[2] for p in all_pos))
    mx = (max(p[0] for p in all_pos), max(p[1] for p in all_pos),
          max(p[2] for p in all_pos))
    return Placement(placed, occupancy, net_sources, net_sinks,
                     primary_inputs, primary_outputs, (mn, mx), out_stubs)


def total_length(pl):
    tot = 0
    for n, ks in pl.net_sinks.items():
        s = pl.net_sources.get(n)
        if not s:
            continue
        for k in ks:
            tot += abs(s[0]-k[0]) + abs(s[2]-k[2])
    return tot


def main():
    nls = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    nl = nls[mod]
    from placer import place
    pl_now = place(nl, col_gap=16, row_gap=16)
    mn, mx = pl_now.bounds
    print(f"[{mod}] current: bbox {mx[0]-mn[0]+1}x{mx[2]-mn[2]+1}, "
          f"total length {total_length(pl_now)}")
    for lpc in (2, 3, 4):
        try:
            plf = fold_place(nl, levels_per_col=lpc, col_gap=16, row_gap=16)
            mn, mx = plf.bounds
            print(f"  fold {lpc}/col: bbox {mx[0]-mn[0]+1}x{mx[2]-mn[2]+1}, "
                  f"total length {total_length(plf)}")
        except Exception as e:
            print(f"  fold {lpc}/col: ERROR {type(e).__name__}: {str(e)[:60]}")


if __name__ == "__main__":
    main()
