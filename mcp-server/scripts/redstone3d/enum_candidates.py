"""
enum_candidates.py — STAGE 1 of the enumeration plan (broad first, narrow later).

Measured on alu1: 9 sinks stay unfed, the joint space is 150^9 (hopeless to
enumerate jointly) BUT each sink sits in a box that is 70-87% EMPTY. So the
failures are bad local choices, not lack of room. That makes the tractable
formulation:

  1. per sink, enumerate EVERY delivery candidate (this file)
  2. each candidate = the exact set of voxels it would occupy
  3. pick one candidate per sink such that no two conflict  <- exact cover,
     GPU-friendly (conflict matrix + bitset search)

This file only does step 1+2: broad, no pruning, so nothing is lost. Narrowing
comes later once we know which candidate classes ever participate in a solution.

A candidate is (cross_y, kind, params) where kind is "stair" or "tower":
  stair: dz row offset, the staircase cells, the jog, the seats
  tower: (arm, side) rotation, the 2x2 shaft voxels
For each we record:
  cond  : conducting voxels (dust/repeater/torch) -> conflict if adjacent
  solid : support/block voxels -> conflict only if they overwrite a conductor
  seats : cells that must stay AIR for a staircase step to conduct
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter, _PLANE_SHELL
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)),
        ((0, 1), (1, 0)), ((1, 0), (0, 1)),
        ((1, 0), (0, -1)), ((0, -1), (1, 0)))
DZS = (0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5, 6, -6, 7, -7, 8, -8)


def stair_candidate(gx, gz, y0, cy, dz):
    """Geometry of a west-side staircase delivery on row gz+dz."""
    depth = cy + 1 - y0
    zz = gz + dz
    cells = [(gx - depth + i, zz) for i in range(1, depth + 1)]
    cond, solid, seats = [], [], []
    cyy = cy + 1
    for (cx, cz) in cells:
        cyy -= 1
        if cyy > y0:
            solid.append((cx, cyy - 1, cz))
            cond.append((cx, cyy, cz))
        else:
            cond.append((cx, y0, cz))
        seats.append((cx, cyy + 1, cz))
    jog = []
    if zz != gz:
        step = 1 if gz > zz else -1
        for t in range(zz, gz + step, step):
            jog.append((gx, t))
    else:
        jog = [(gx, gz)]
    for (jx, jz) in jog:
        cond.append((jx, y0, jz))
    return {"kind": "stair", "cy": cy, "dz": dz,
            "cond": cond, "solid": solid, "seats": seats,
            "plane": list(cells) + jog}


def tower_candidate(gx, gz, y0, cy, arm, side):
    """Geometry of a 2x2 down-tower delivery in the pin's feed column."""
    feed = (gx - 1, gz)
    y_from = cy
    if y_from <= y0:
        return None
    cells, foot = down_tower_cells_dir(feed[0], feed[1], y_from, y0,
                                       side=side, arm=arm)
    cond, solid = [], []
    for (x, y, z, b) in cells:
        if b == DUST or "torch" in b:
            cond.append((x, y, z))
        else:
            solid.append((x, y, z))
    cond.append((feed[0], y0, feed[1]))
    cond.append((feed[0], cy, feed[1]))          # the stair-in dust
    return {"kind": "tower", "cy": cy, "rot": (arm, side),
            "cond": cond, "solid": solid, "seats": [],
            "plane": sorted(foot)}


def enumerate_for_sink(gx, gz, y0, layers):
    out = []
    for cy in layers:
        for dz in DZS:
            out.append(stair_candidate(gx, gz, y0, cy, dz))
        for arm, side in ROTS:
            t = tower_candidate(gx, gz, y0, cy, arm, side)
            if t:
                out.append(t)
    return out


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=rounds)
    y0 = pl.bounds[0][1]

    own_by_net = {}
    for n in res.wires:
        own_by_net[n] = {(p[0], p[2]) for p in res.wires[n]} | \
                        {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
    unfed = []
    for n in res.failed:
        for k in pl.net_sinks.get(n, []):
            if (k[0]-1, k[2]) not in own_by_net.get(n, ()):
                unfed.append((n, (k[0], k[2])))

    # BROAD: every cross layer the router would ever consider
    layers = [y0 + 4 * i for i in range(1, 7)]
    print(f"[{mod}] unfed sinks={len(unfed)}  cross layers={layers}")

    # baseline occupancy from the SUCCESSFUL part of the route (what candidates
    # must avoid). conducting voxels only.
    occupied = {}
    for n, ws in res.wires.items():
        for p in ws:
            occupied[p] = n
    for n, reps in res.repeaters.items():
        for (q, _f) in reps:
            occupied[q] = n
    for p in res.torches:
        occupied[p] = res.torch_nets.get(p, "?")
    for (q, b) in res.wall_torches:
        occupied[q] = res.wall_torch_nets.get(q, "?")

    dump = {"module": mod, "y0": y0, "layers": layers,
            "occupied": [[k[0], k[1], k[2], v] for k, v in occupied.items()],
            "cell_xz": [list(c) for c in r.cell_xz],
            "pin_xz": [[c[0], c[1], n] for c, n in r.pin_net.items()],
            "sinks": []}
    total = 0
    for n, (gx, gz) in unfed:
        cands = enumerate_for_sink(gx, gz, y0, layers)
        # quick static filter ONLY on hard blockers (gate bodies / pins): keeps
        # the space broad but drops candidates that are impossible by geometry
        keep = []
        for c in cands:
            if any((p[0], p[2]) in r.cell_xz or (p[0], p[2]) in r.pin_net
                   for p in c["cond"]):
                continue
            keep.append(c)
        total += len(keep)
        dump["sinks"].append({"net": n, "pin": [gx, gz],
                              "cands": [{"kind": c["kind"], "cy": c["cy"],
                                         "dz": c.get("dz"),
                                         "rot": c.get("rot"),
                                         "cond": [list(v) for v in c["cond"]],
                                         "solid": [list(v) for v in c["solid"]],
                                         "seats": [list(v) for v in c["seats"]]}
                                        for c in keep]})
        print(f"  {n}@({gx},{gz}): {len(cands)} raw -> {len(keep)} geometrically viable")
    print(f"total candidates across sinks: {total}")
    out = os.path.join(base, f"{mod}_cands.json")
    json.dump(dump, open(out, "w"))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
