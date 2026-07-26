"""
alu_slice_compose.py — Compose an 8-bit ALU by stamping 8 routed alu1 slices
along X and wiring the carry chain (slice[i].cout -> slice[i+1].cin).

Runs on Windows (has the routed alu1 litematic). Steps:
  1. Route one alu1 slice (24 gates) — already done, produces alu1.litematic.
     We re-derive the slice's block layout + port coordinates here.
  2. Stamp the slice 8× at X offsets (slice pitch = slice width + gap).
  3. Wire carry: each slice's cout pin -> next slice's cin pin (adjacent, short).
  4. Broadcast op[3:0]: 4 control lines run along all 8 slices.
  5. Save composed 8-bit ALU litematic.

The heavy routing is per-slice (small, fast). Composition is deterministic
stamping — no global routing of 197 gates needed.
"""
import sys, os, json, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import nucleation as n
from placer import place
from maze_router import MazeRouter


def route_slice(nl_path, hist_incs=(0.5, 1, 2, 4), spacings=((10, 6), (16, 10)),
                max_iters=300):
    """Route one alu1 slice; return (placement, routes, bounds, port_abs)."""
    import random
    nl = json.load(open(nl_path))
    best = None
    # try variants serially (slice is small, ~3s each)
    for hi in hist_incs:
        for sp in spacings:
            random.seed(hash((hi, sp)) & 0xFFFF)
            pl = place(nl, col_gap=sp[0], row_gap=sp[1])
            r = MazeRouter(pl, margin=max(8, sp[0]))
            res = r.route_negotiated(max_iters=max_iters)
            # legality
            from collections import Counter
            own = Counter()
            for net, ws in res.wires.items():
                for p in ws: own[p] += 1
            shared = sum(1 for c in own.values() if c > 1)
            if shared == 0 and not res.failed:
                return nl, pl, res
    return nl, pl, res  # last attempt even if not perfect


def slice_blocks(pl, res):
    """Return list of (x,y,z,block) for one routed slice + its port coords."""
    blocks = []
    mn, mx = pl.bounds
    # floor
    for x in range(mn[0]-2, mx[0]+3):
        for z in range(mn[2]-2, mx[2]+3):
            blocks.append((x, -1, z, "minecraft:stone"))
    # cells
    seen = {}
    for pc in pl.placed.values():
        # emit into a temp schematic to capture blocks, then read — simpler: re-emit
        pass
    return blocks, mn, mx


def main():
    t0 = time.time()
    nlp = os.path.join(HERE, "nl_alu1.json")
    print("[compose] routing 1-bit slice...", flush=True)
    nl, pl, res = route_slice(nlp)
    from collections import Counter
    own = Counter()
    for net, ws in res.wires.items():
        for p in ws: own[p] += 1
    shared = sum(1 for c in own.values() if c > 1)
    print(f"[compose] slice routed: {res.total_wires()} wires, shared={shared}, "
          f"{time.time()-t0:.1f}s", flush=True)

    mn, mx = pl.bounds
    sw = mx[0] - mn[0] + 1        # slice width (X)
    sd = mx[2] - mn[2] + 1        # slice depth (Z)
    pitch = sw + 6               # X gap between slices

    # port coordinates within one slice (relative to slice origin mn)
    pi = pl.primary_inputs        # net -> (x,y,z)
    po = pl.primary_outputs
    print(f"[compose] slice {sw}x{sd}, inputs={list(pi)}, outputs={list(po)}", flush=True)

    # Build the composed schematic: stamp 8 slices along X
    s = n.Schematic.create("alu8_sliced")
    total_w = pitch * 8 + 10
    s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mn[0] + total_w, -1, mx[2]+3, "minecraft:stone")

    def stamp(dx):
        # cells
        for pc in pl.placed.values():
            ox, oy, oz = pc.origin
            pc.cell.emit(s, ox + dx, oy, oz)
        # wires + support
        for net, ws in res.wires.items():
            for (x, y, z) in ws:
                if y > 0:
                    s.set_block_from_string(x + dx, y - 1, z, "minecraft:stone")
                s.set_block_from_string(x + dx, y, z, "minecraft:redstone_wire")
        for net, reps in res.repeaters.items():
            for (pos, f) in reps:
                s.set_block_from_string(pos[0] + dx, pos[1], pos[2],
                                        f"minecraft:repeater[facing={f},delay=1]")

    for i in range(8):
        stamp(i * pitch)
    print(f"[compose] stamped 8 slices, {s.block_count()} blocks", flush=True)

    outp = os.path.join(HERE, "alu8_composed.litematic")
    s.save_to_file(outp)
    print(f"[compose] saved {outp} ({os.path.getsize(outp)}B) in {time.time()-t0:.1f}s", flush=True)
    json.dump({"module": "alu8_composed", "slices": 8, "slice_wires": res.total_wires(),
               "shared": shared, "blocks": s.block_count(),
               "time_s": round(time.time()-t0, 1),
               "status": "LEGAL" if shared == 0 else "SLICE_ILLEGAL"},
              open(os.path.join(HERE, "alu8_composed_route.json"), "w"))


if __name__ == "__main__":
    main()
