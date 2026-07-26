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
    pitch = sw + 8               # X gap between slices (room for connector wires)

    # port coordinates within one slice (relative to slice origin, mn=(0,0,0))
    pi = pl.primary_inputs        # net -> (x,y,z)  — west edge
    po = pl.primary_outputs       # net -> (x,y,z)  — east edge
    pb = nl["port_bits"]
    def netpos_in(port, i=0):
        b = pb[port][i]; return pi[f"n{b}"]
    def netpos_out(port, i=0):
        b = pb[port][i]; return po[f"n{b}"]
    cin_p  = netpos_in("cin")     # (0,0,4)
    cout_p = netpos_out("cout")   # (192,0,1)
    a_p    = netpos_in("a")       # (0,0,0)
    b_p    = netpos_in("b")       # (0,0,2)
    op_ps  = [netpos_in("op", i) for i in range(4)]  # z=6,8,10,12
    y_p    = netpos_out("y")
    print(f"[compose] slice {sw}x{sd} cin={cin_p} cout={cout_p} op={op_ps}", flush=True)

    s = n.Schematic.create("alu8_sliced")
    total_w = pitch * 8 + 20
    # extend floor in +Z for the op broadcast bus lanes below the slices
    zbus0 = mx[2] + 2                     # op bus starts just south of slices
    s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mn[0] + total_w, -1, zbus0 + 12, "minecraft:stone")

    def wire(x, y, z):
        if y > 0: s.set_block_from_string(x, y-1, z, "minecraft:stone")
        s.set_block_from_string(x, y, z, "minecraft:redstone_wire")

    def rep(x, y, z, facing):
        if y > 0: s.set_block_from_string(x, y-1, z, "minecraft:stone")
        s.set_block_from_string(x, y, z, f"minecraft:repeater[facing={facing},delay=1]")

    def stamp(dx):
        for pc in pl.placed.values():
            ox, oy, oz = pc.origin
            pc.cell.emit(s, ox + dx, oy, oz)
        for net, ws in res.wires.items():
            for (x, y, z) in ws:
                wire(x + dx, y, z)
        for net, reps in res.repeaters.items():
            for (pos, f) in reps:
                rep(pos[0] + dx, pos[1], pos[2], f)

    for i in range(8):
        stamp(i * pitch)
    print(f"[compose] stamped 8 slices, {s.block_count()} blocks", flush=True)

    # ---- Inter-slice connector wiring ----
    # 1. Carry chain: slice[i].cout (east) -> slice[i+1].cin (west of next slice).
    #    cout is at x=cout_p[0]+i*pitch ; next cin at x=cin_p[0]+(i+1)*pitch.
    #    Route along a free Z lane (z = cin_p[2]) with repeaters every 15 blocks.
    for i in range(7):
        cout_abs = (cout_p[0] + i*pitch, cout_p[1], cout_p[2])
        cin_abs  = (cin_p[0] + (i+1)*pitch, cin_p[1], cin_p[2])
        # route: from cout east to a vertical Z lane at x just past this slice,
        # down to cin's z, then east into next slice's cin
        lane_x = mn[0] + i*pitch + sw + 2   # in the gap after slice i
        # horizontal from cout to lane
        z = cout_abs[2]
        run = 0
        for x in range(cout_abs[0]+1, lane_x+1):
            wire(x, 0, z); run += 1
            if run % 15 == 0: rep(x, 0, z, "west")
        # vertical along lane_x from cout z to cin z
        z0, z1 = sorted([cout_abs[2], cin_abs[2]])
        for zz in range(z0, z1+1):
            wire(lane_x, 0, zz)
        # horizontal from lane to next cin
        run = 0
        for x in range(lane_x, cin_abs[0]):
            wire(x, 0, cin_abs[2]); run += 1
            if run % 15 == 0: rep(x, 0, cin_abs[2], "west")

    # 2. bit0 cin = is_sub. For a self-contained buildable demo we expose cin[0],
    #    a[i], b[i], op[3:0] as lever inputs on the west edge of each slice —
    #    those pins are already primary inputs; leave them as wire stubs for the
    #    builder to drive. (op broadcast bus below is optional convenience.)
    # 3. op[3:0] broadcast bus: 4 Z-lanes south of the slices, each op line runs
    #    the full width and taps up into every slice's op pin.
    for k in range(4):
        bus_z = zbus0 + k*2
        # full-width bus lane
        run = 0
        for x in range(mn[0], mn[0] + pitch*8):
            wire(x, 0, bus_z); run += 1
            if run % 15 == 0: rep(x, 0, bus_z, "west")
        # tap into each slice's op[k] pin (at z=op_ps[k][2]) via a short Z spur
        for i in range(8):
            px = op_ps[k][0] + i*pitch
            z0, z1 = sorted([op_ps[k][2], bus_z])
            for zz in range(z0, z1+1):
                wire(px, 0, zz)
    print(f"[compose] wired carry chain + op bus, {s.block_count()} blocks", flush=True)

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
