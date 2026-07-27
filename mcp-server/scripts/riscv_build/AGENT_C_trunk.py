#!/usr/bin/env python3
"""
AGENT_C_trunk.py — Trunk-and-Branch routing for high-fanout nets on the y=0 plane.

PROBLEM:
  High-fanout nets (primary inputs, control buses) fan out to gates scattered
  across the whole layout.  On a single y=0 plane these broadcast nets cannot
  reach all sinks without crossing other nets, forcing expensive bridges to
  y>0 layers.

STRATEGY (Trunk-and-Branch):
  1. Identify high-fanout nets (>= 3 sinks).
  2. Reserve dedicated z-lanes for these nets.
  3. BUILD ALL TRUNKS FIRST: place horizontal wires in routing channels only.
     Trunks do NOT include risers or source connections at this stage.
  4. THEN connect each high-fanout net's source to its trunk via BFS.
  5. THEN route branches from the tree to each sink (short BFS paths).
  6. Route remaining (low-fanout) nets with the baseline 2D BFS.
  7. Since trunks run on parallel z-lanes with >= 3-block separation, they
     can never cross or short each other.

The split-phase construction (trunks first, then connections) avoids the
order-dependent conflict where one net's riser blocks another net's source.

MEASURE:
  - Baseline: plain greedy 2D BFS router with 8-neighbourhood short-rejection.
  - Trunk-and-Branch: same router but with high-fanout nets pre-routed on lanes.
  - Compare (net, sink) pairs that still cannot be reached flat (need a bridge).
"""

from __future__ import annotations
import sys
import os
from collections import deque, defaultdict
from typing import Dict, List, Tuple, Set, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
from yosys_frontend import compile_verilog
from placer import place, Placement

_SHELL = [(1, 0), (-1, 0), (0, 1), (0, -1),
          (1, 1), (1, -1), (-1, 1), (-1, -1)]
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
LANE_SEP = 3
HF_THRESHOLD = 3


# =========================================================================
#  Column / routing-channel x-ranges
# =========================================================================

def get_column_xranges(pl: Placement) -> List[Tuple[int, int]]:
    spans = [(pc.origin[0], pc.origin[0] + pc.cell.width - 1) for pc in pl.placed.values()]
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if not merged or s > merged[-1][1] + 1:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
    return merged


def get_routing_channel_xranges(col_xranges: List[Tuple[int, int]], bx: Tuple[int, int]) -> List[Tuple[int, int]]:
    channels: List[Tuple[int, int]] = []
    cur = bx[0]
    for cs, ce in col_xranges:
        if cur < cs:
            channels.append((cur, cs - 1))
        cur = ce + 1
    if cur <= bx[1]:
        channels.append((cur, bx[1]))
    return channels


# =========================================================================
#  2D BFS
# =========================================================================

def _bfs_2d(
    sources: Set[Tuple[int, int]],
    targets: Set[Tuple[int, int]],
    net: str,
    wire_owner: Dict[Tuple[int, int], str],
    occ_xz: Set[Tuple[int, int]],
    pin_xz: Set[Tuple[int, int]],
    bx: Tuple[int, int],
    bz: Tuple[int, int],
) -> Optional[List[Tuple[int, int]]]:
    prev: Dict[Tuple[int, int], Tuple[int, int]] = {}
    _seen: Set[Tuple[int, int]] = set(sources)
    q = deque(sources)

    def _foreign_adj(xz):
        for dx, dz in _SHELL:
            qq = (xz[0] + dx, xz[1] + dz)
            o = wire_owner.get(qq)
            if o is not None and o != net:
                return True
        return False

    while q:
        cur = q.popleft()
        if cur in targets:
            path = [cur]
            while path[-1] in prev:
                path.append(prev[path[-1]])
            path.reverse()
            return path
        for dx, dz in _H:
            nx = (cur[0] + dx, cur[1] + dz)
            if nx in _seen:
                continue
            if nx not in targets:
                if not (bx[0] <= nx[0] <= bx[1] and bz[0] <= nx[1] <= bz[1]):
                    continue
                if nx in occ_xz and nx not in pin_xz:
                    continue
                o = wire_owner.get(nx)
                if o is not None and o != net:
                    continue
                if _foreign_adj(nx):
                    continue
            _seen.add(nx)
            prev[nx] = cur
            q.append(nx)
    return None


# =========================================================================
#  Lane assignment
# =========================================================================

def find_free_lanes(occ_xz: Set, bx: Tuple[int, int], bz: Tuple[int, int]) -> List[int]:
    free: List[int] = []
    for z in range(bz[0], bz[1] + 1):
        ok = True
        for x in range(bx[0], bx[1] + 1):
            if (x, z) in occ_xz:
                ok = False
                break
        if ok:
            free.append(z)
    return free


def assign_lanes(hf_nets: List[str], free_lanes: List[int]) -> Dict[str, int]:
    assigned: Dict[str, int] = {}
    used: List[int] = []
    for net in hf_nets:
        for z in free_lanes:
            if all(abs(z - uz) >= LANE_SEP for uz in used):
                assigned[net] = z
                used.append(z)
                break
    return assigned


# =========================================================================
#  Trunk-and-Branch router  (SPLIT-PHASE: trunks first, then connections)
# =========================================================================

def trunk_branch_route_2d(
    pl: Placement,
    margin: int = 10,
    hf_threshold: int = HF_THRESHOLD,
) -> Tuple[List[Tuple[str, Tuple[int, int, int]]], Dict[str, int], dict]:
    mn, mx = pl.bounds
    bx = (mn[0] - margin, mx[0] + margin)
    bz = (mn[2] - margin, mx[2] + margin)

    # ---- Occupancy & pins ----
    occ_xz: Set[Tuple[int, int]] = set()
    for p in pl.occupancy:
        occ_xz.add((p[0], p[2]))

    pin_xz: Set[Tuple[int, int]] = set()
    for pc in pl.placed.values():
        for pos in pc.input_pins.values():
            pin_xz.add((pos[0], pos[2]))
        for pos in pc.output_pins.values():
            pin_xz.add((pos[0], pos[2]))
    for pos in pl.primary_inputs.values():
        pin_xz.add((pos[0], pos[2]))

    wire_owner: Dict[Tuple[int, int], str] = {}

    # ---- Classify nets ----
    all_nets = [n for n in pl.net_sinks if pl.net_sources.get(n) and pl.net_sinks.get(n)]
    high_fanout = sorted(
        [n for n in all_nets if len(pl.net_sinks[n]) >= hf_threshold],
        key=lambda n: len(pl.net_sinks[n]), reverse=True,
    )
    hf_set = set(high_fanout)
    other_nets = [n for n in all_nets if n not in hf_set]

    # ---- Lanes ----
    free_lanes = find_free_lanes(occ_xz, bx, bz)
    lane_assign = assign_lanes(high_fanout, free_lanes)
    unassigned = [n for n in high_fanout if n not in lane_assign]
    other_nets.extend(unassigned)

    # ---- Routing channels ----
    col_xranges = get_column_xranges(pl)
    route_ch_xranges = get_routing_channel_xranges(col_xranges, bx)

    # ---- Phase 1: Build ALL trunks first (no risers/source connections) ----
    trunk_sets: Dict[str, Set[Tuple[int, int]]] = {}

    for net in high_fanout:
        lane_z = lane_assign.get(net)
        if lane_z is None:
            continue

        sinks = pl.net_sinks[net]
        sink_xs = [s[0] for s in sinks]
        x_lo = max(bx[0], min(sink_xs) - 2)
        x_hi = min(bx[1], max(sink_xs) + 2)

        trunk: Set[Tuple[int, int]] = set()
        for rcs, rce in route_ch_xranges:
            for x in range(max(x_lo, rcs), min(x_hi, rce) + 1):
                p = (x, lane_z)
                if p in occ_xz and p not in pin_xz:
                    continue
                # Check no foreign adjacency
                foreign = False
                for dx, dz in _SHELL:
                    qq = (p[0] + dx, p[1] + dz)
                    o = wire_owner.get(qq)
                    if o is not None and o != net:
                        foreign = True
                        break
                if foreign:
                    continue
                trunk.add(p)
                wire_owner[p] = net  # claim immediately

        trunk_sets[net] = trunk

    # ---- Phase 2: Connect sources and branches (BFs after all trunks placed) ----
    failed_pairs: List[Tuple[str, Tuple[int, int, int]]] = []

    for net in high_fanout:
        lane_z = lane_assign.get(net)
        if lane_z is None:
            continue
        trunk = trunk_sets.get(net, set())
        if not trunk:
            other_nets.append(net)
            continue

        src = pl.net_sources[net]
        src_xz = (src[0], src[2])
        sinks = pl.net_sinks[net]

        # Register source
        wire_owner.setdefault(src_xz, net)
        tree: Set[Tuple[int, int]] = {src_xz}

        # If source is not in/wired to trunk, BFS
        if src_xz not in trunk:
            path = _bfs_2d({src_xz}, trunk, net, wire_owner, occ_xz, pin_xz, bx, bz)
            if path:
                for p in path:
                    wire_owner[p] = net
                    tree.add(p)

        # Add remaining trunk points
        for p in trunk:
            tree.add(p)

        # Route branches
        for sink in sinks:
            sink_xz = (sink[0], sink[2])
            if sink_xz in tree or wire_owner.get(sink_xz) == net:
                continue
            path = _bfs_2d(tree, {sink_xz}, net, wire_owner, occ_xz, pin_xz, bx, bz)
            if path:
                for p in path:
                    wire_owner[p] = net
                    tree.add(p)
            else:
                failed_pairs.append((net, sink))

    # ---- Phase 3: Route remaining nets greedily ----
    def _span(n):
        s = pl.net_sources[n]
        ks = pl.net_sinks[n]
        return max(abs(s[0] - k[0]) + abs(s[2] - k[2]) for k in ks)

    other_nets.sort(key=_span)

    for net in other_nets:
        src = pl.net_sources[net]
        src_xz = (src[0], src[2])
        wire_owner.setdefault(src_xz, net)
        tree = {src_xz}
        for sink in sorted(pl.net_sinks[net],
                           key=lambda k: abs(src[0] - k[0]) + abs(src[2] - k[2])):
            sink_xz = (sink[0], sink[2])
            if sink_xz in tree or wire_owner.get(sink_xz) == net:
                continue
            path = _bfs_2d(tree, {sink_xz}, net, wire_owner, occ_xz, pin_xz, bx, bz)
            if path:
                for p in path:
                    wire_owner[p] = net
                    tree.add(p)
            else:
                failed_pairs.append((net, sink))

    # ---- Stats ----
    stats = {
        "total_nets": len(all_nets),
        "total_sinks": sum(len(pl.net_sinks[n]) for n in all_nets),
        "hf_nets": len(high_fanout),
        "hf_assigned": len(lane_assign),
        "free_lanes_avail": len(free_lanes),
        "failed_sinks": len(failed_pairs),
        "failed_nets": len({n for n, _ in failed_pairs}),
        "total_wires": len(wire_owner),
    }
    return failed_pairs, lane_assign, stats


# =========================================================================
#  Baseline (same 2D BFS, no trunk reservation)
# =========================================================================

def baseline_route_2d(pl: Placement, margin: int = 10) -> Tuple[List[Tuple[str, Tuple[int, int, int]]], int]:
    mn, mx = pl.bounds
    bx = (mn[0] - margin, mx[0] + margin)
    bz = (mn[2] - margin, mx[2] + margin)
    occ_xz = set((p[0], p[2]) for p in pl.occupancy)
    pin_xz = set()
    for pc in pl.placed.values():
        for pos in pc.input_pins.values(): pin_xz.add((pos[0], pos[2]))
        for pos in pc.output_pins.values(): pin_xz.add((pos[0], pos[2]))
    for pos in pl.primary_inputs.values(): pin_xz.add((pos[0], pos[2]))
    wire_owner: Dict = {}
    all_nets = [n for n in pl.net_sinks if pl.net_sources.get(n) and pl.net_sinks.get(n)]
    all_nets.sort(key=lambda n: max(abs(pl.net_sources[n][0] - k[0]) + abs(pl.net_sources[n][2] - k[2]) for k in pl.net_sinks[n]))
    failed = []
    for net in all_nets:
        src = pl.net_sources[net]; src_xz = (src[0], src[2])
        wire_owner.setdefault(src_xz, net); tree = {src_xz}
        for sink in sorted(pl.net_sinks[net], key=lambda k: abs(src[0]-k[0])+abs(src[2]-k[2])):
            sxz = (sink[0], sink[2])
            if sxz in tree: continue
            p = _bfs_2d(tree, {sxz}, net, wire_owner, occ_xz, pin_xz, bx, bz)
            if p:
                for pp in p: wire_owner[pp] = net; tree.add(pp)
            else: failed.append((net, sink))
    return failed, len(wire_owner)


# =========================================================================
#  Reporting
# =========================================================================

def analyze_by_net(fp):
    d = defaultdict(list)
    for n, s in fp: d[n].append(s)
    return dict(d)


def print_failure_table(by_net, label):
    if not by_net: print(f"  {label}: ALL SINKS REACHED (0)"); return
    print(f"  {label}:")
    for n in sorted(by_net):
        print(f"    {n:>8s}: {len(by_net[n])} sink(s)")
    total = sum(len(v) for v in by_net.values())
    print(f"    {'Total':>8s}: {total} sinks across {len(by_net)} nets")


def main():
    print("=" * 72)
    print("  AGENT C: Trunk-and-Branch Routing for High-Fanout Nets")
    print("  Split-phase: trunks first, then connections via BFS")
    print("=" * 72)

    vpath = os.path.join(HERE, "..", "riscv_synth", "alu1.v")
    print(f"\n  Compiling {vpath} ...", end=" ", flush=True)
    nl = compile_verilog(vpath, top="alu1")
    print(f"done.  {len(nl['cells'])} gates, {len(nl.get('inputs', []))} PIs")
    print(f"  Inputs: {nl.get('inputs', [])}")

    spacings = [(16, 10), (24, 14), (32, 20), (48, 30)]
    rows = []

    for cg, rg in spacings:
        print(f"\n  {'=' * 68}")
        print(f"  Spacing: col_gap={cg}, row_gap={rg}")
        print(f"  {'=' * 68}")
        pl = place(nl, col_gap=cg, row_gap=rg)
        mn, mx = pl.bounds
        dim = (mx[0] - mn[0], mx[2] - mn[2])
        print(f"  Placement: {dim[0]} x {dim[1]}")

        hf = sorted([n for n in pl.net_sinks if len(pl.net_sinks[n]) >= HF_THRESHOLD],
                     key=lambda n: len(pl.net_sinks[n]), reverse=True)
        print(f"  High-fanout: {len(hf)} nets")
        for n in hf:
            sks = "; ".join(f"({s[0]},{s[2]})" for s in pl.net_sinks[n])
            src = pl.net_sources[n]
            print(f"    {n:>8s}: src=({src[0]},{src[2]}) -> [{sks}]")

        # Baseline
        b_fail, b_w = baseline_route_2d(pl, margin=cg)
        b_bn = analyze_by_net(b_fail)

        # Trunk+Branch
        tb_fail, la, s = trunk_branch_route_2d(pl, margin=cg)
        tb_bn = analyze_by_net(tb_fail)

        # Print
        print(f"\n  {'Metric':<32} {'Baseline':>10} {'T+B':>10}")
        print(f"  {'—' * 32}  {'—' * 10}  {'—' * 10}")
        print(f"  {'Wires':<32} {b_w:>10} {s['total_wires']:>10}")
        print(f"  {'Failed sinks':<32} {len(b_fail):>10} {s['failed_sinks']:>10}")
        print(f"  {'Failed nets':<32} {len(b_bn):>10} {s['failed_nets']:>10}")
        print(f"  {'Free lanes':<32} {'—':>10} {s['free_lanes_avail']:>10}")
        if la:
            print(f"  Lane assign:", {k: v for k, v in la.items()})

        print()
        print_failure_table(b_bn, "BASELINE")
        print()
        print_failure_table(tb_bn, "T+B")

        # Per-net
        impr = len(b_fail) - len(tb_fail)
        pct = (impr / max(len(b_fail), 1)) * 100
        print(f"\n  Δ: {impr:+d}/{len(b_fail)} ({pct:+.0f}%)")

        print(f"\n  {'Net':>8s} {'BL':>4s} {'TB':>4s} {'Δ':>6s}")
        print(f"  {'—' * 8} {'—' * 4} {'—' * 4} {'—' * 6}")
        all_af = set(b_bn) | set(tb_bn)
        for n in sorted(all_af, key=lambda x: len(pl.net_sinks[x]), reverse=True):
            bc = len(b_bn.get(n, []))
            tc = len(tb_bn.get(n, []))
            d = bc - tc
            ds = f"+{d}" if d > 0 else (str(d) if d < 0 else " 0")
            tag = ""
            if d > 0 and tc == 0: tag = " ★ FIXED"
            elif d > 0: tag = " (better)"
            elif d < 0 and bc == 0: tag = " ★ NEW"
            elif d < 0: tag = " (worse)"
            print(f"  {n:>8s} {bc:>4d} {tc:>4d} {ds:>6s}{tag}")

        bg = set(pl.net_sinks) - set(b_bn)
        tg = set(pl.net_sinks) - set(tb_bn)
        if bg - tg: print(f"  REGRESSED: {sorted(bg - tg)}")
        if tg - bg: print(f"  IMPROVED:  {sorted(tg - bg)}")

        rows.append({
            "sp": (cg, rg), "dim": dim, "bf": len(b_fail), "tf": len(tb_fail),
            "impr": impr, "pct": pct,
            "impr_nets": sorted(tg - bg), "reg_nets": sorted(bg - tg),
        })

    # Summary
    print(f"\n{'=' * 72}")
    print(f"  SUMMARY — alu1 ({len(nl['cells'])} gates)")
    print(f"{'=' * 72}")
    print(f"  {'Spacing':>10} {'Dims':>10} {'Base':>6} {'TB':>6} {'Δ':>6}")
    print(f"  {'—' * 10} {'—' * 10} {'—' * 6} {'—' * 6} {'—' * 6}")
    for r in rows:
        cg, rg = r["sp"]
        ds = f"{r['dim'][0]}x{r['dim'][1]}"
        d = r["impr"]
        ds2 = f"+{d}" if d > 0 else (str(d) if d < 0 else "  0")
        print(f"  ({cg:>3},{rg:>3}) {ds:>10} {r['bf']:>6} {r['tf']:>6} {ds2:>6}")

    all_impr = set(); all_reg = set()
    for r in rows:
        all_impr.update(r["impr_nets"]); all_reg.update(r["reg_nets"])
    if all_impr: print(f"\n  Improved nets  (cross-spacing): {sorted(all_impr)}")
    if all_reg: print(f"  Regressed nets (cross-spacing): {sorted(all_reg)}")

    best = max(r["impr"] for r in rows) if rows else 0
    best_sp = [r["sp"] for r in rows if r["impr"] == best]
    print(f"\n  Best Δ: {best:+d} at {best_sp}")
    if best > 0:
        print(f"  Verdict: Trunk+branch REDUCES bridges by {best} for alu1")
    elif best == 0:
        print(f"  Verdict: Trunk+branch is neutral (same total bridges)")
    else:
        print(f"  Verdict: Trunk+branch INCREASES bridges by {-best}")


if __name__ == "__main__":
    main()
