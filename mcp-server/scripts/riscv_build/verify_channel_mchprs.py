"""verify_channel_mchprs.py — MCHPRS verification for the 2-layer ChannelRouter."""
import sys, os, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "redstone3d"))
sys.path.insert(0, os.path.join(HERE, "..", "riscv_synth"))
import nucleation as nuc
from placer import place
from route_channel import ChannelRouter
from yosys_frontend import compile_verilog
from mchprs_sim import simulate_vectors, report

W = "minecraft:redstone_wire"; S = "minecraft:stone"; RB = "minecraft:redstone_block"


def legality(res, pl):
    """Count shorts (8-neighbor same-y + vertical y±1) and floats (y>base y
    dust without a support/occupancy below). Returns (shorts, floats)."""
    owner = dict(res.wire_owner)
    SHELL = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
    shorts = 0
    floats = 0
    sup = res.supports
    occ = set(pl.occupancy)
    base_y = pl.bounds[0][1]

    for p, net in owner.items():
        x, y, z = p
        # Same-y 8-neighbor
        for dx, dz in SHELL:
            o = owner.get((x+dx, y, z+dz))
            if o is not None and o != net:
                shorts += 1
        # Vertical y±1
        for dy in (1, -1):
            o = owner.get((x, y+dy, z))
            if o is not None and o != net:
                shorts += 1
        # Float check: every y > base_y dust needs a solid support below
        if y > base_y:
            below = (x, y-1, z)
            if below not in sup and below not in occ and below not in owner:
                floats += 1

    return shorts // 2, floats  # each short counted twice


def emit(schem, pl, res, inputs):
    """Build the schematic for MCHPRS simulation.
    Places floor, cell bodies, router wires/supports/repeaters/torches, and input blocks.
    """
    B = schem.set_block_from_string
    mn, mx = pl.bounds

    # Collect bounds of everything
    xs = [mn[0], mx[0]]
    zs = [mn[2], mx[2]]
    for w in res.wires.values():
        for p in w:
            xs.append(p[0]); zs.append(p[2])
    for p in res.supports:
        xs.append(p[0]); zs.append(p[2])
    for reps in res.repeaters.values():
        for pos, _f in reps:
            xs.append(pos[0]); zs.append(pos[2])
    for p in res.torches:
        xs.append(p[0]); zs.append(p[2])

    # Floor at y = base_y - 1
    fy = mn[1] - 1
    min_x, max_x = min(xs) - 2, max(xs) + 3
    min_z, max_z = min(zs) - 2, max(zs) + 3
    for x in range(min_x, max_x):
        for z in range(min_z, max_z):
            B(x, fy, z, S)

    # Supports
    for (x, y, z) in res.supports:
        B(x, y, z, S)

    # Cell bodies
    for pc in pl.placed.values():
        pc.cell.emit(schem, *pc.origin)

    # Router wires
    for net, ws in res.wires.items():
        for (x, y, z) in ws:
            B(x, y, z, W)

    # Router repeaters
    for net, reps in res.repeaters.items():
        for (pos, f) in reps:
            B(pos[0], pos[1], pos[2], f"minecraft:repeater[facing={f},delay=1]")

    # Router torches (standing redstone torches)
    for (x, y, z) in res.torches:
        B(x, y, z, "minecraft:redstone_torch")

    # Primary inputs: redstone_block for '1', air for '0'
    for net, pos in pl.primary_inputs.items():
        v = inputs.get(net, 0)
        B(pos[0] - 1, pos[1], pos[2], RB if v else "minecraft:air")
        B(pos[0], pos[1], pos[2], W)


def netname(bit):
    return f"n{bit}" if not isinstance(bit, str) else f"const_{bit}"


if __name__ == "__main__":
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    vf_map = {
        "alu1": "alu1.v",
        "Control": "Control.v",
        "Mux_2to1": "Mux_2to1.v",
        "ALU_Control": "ALU_Control.v",
        "Imm_Gen": "Imm_Gen.v",
    }
    vf = vf_map.get(mod, f"{mod}.v")
    vf_path = os.path.join(HERE, "..", "riscv_synth", vf)

    nl = compile_verilog(vf_path, top=mod)
    print(f"{mod}: {len(nl['cells'])} gates {dict(Counter(c['type'] for c in nl['cells'].values()))}")

    pl = place(nl, col_gap=16, row_gap=10)
    print(f"Placement bounds: {pl.bounds}")

    r = ChannelRouter(pl)
    t0 = time.time()
    res = r.route(verbose=False)
    sh, fl = legality(res, pl)
    print(f"  wires={res.total_wires()} supports={len(res.supports)} "
          f"reps={sum(len(v) for v in res.repeaters.values())} "
          f"shorts={sh} floats={fl} route_time={time.time()-t0:.1f}s")

    if mod == "alu1":
        pb = nl["port_bits"]
        a_n = netname(pb["a"][0])
        b_n = netname(pb["b"][0])
        cin_n = netname(pb["cin"][0])
        op_n = [netname(x) for x in pb["op"]]
        y_n = netname(pb["y"][0])
        cout_n = netname(pb["cout"][0])

        tvs = []
        specs = []
        for op in (0, 1, 2, 3, 6):
            for a in (0, 1):
                for b in (0, 1):
                    for cin in (0, 1):
                        iv = {a_n: a, b_n: b, cin_n: cin}
                        for i in range(4):
                            iv[op_n[i]] = (op >> i) & 1
                        bb = (1 - b) if op == 6 else b
                        summ = a ^ bb ^ cin
                        cout = (a & bb) | (cin & (a ^ bb))
                        yv = {0: a & b, 1: a | b, 2: summ, 3: a ^ b, 6: summ}.get(op, 0)
                        tvs.append(iv)
                        specs.append({y_n: yv, cout_n: cout})

        probes = dict(pl.primary_outputs)

        def build(schem, inputs):
            emit(schem, pl, res, inputs)

        test_vectors = [{"inputs": iv, "expected": sp} for iv, sp in zip(tvs, specs)]
        t1 = time.time()
        results = simulate_vectors(build, list(nl["inputs"]), probes,
                                   test_vectors, ticks=30, lamp_outputs=False)
        report(mod, results)
        print(f"  sim_time={time.time()-t1:.1f}s")

        total = len(results)
        passed = sum(1 for r in results if r["match"])
        print(f"\n  VERDICT: {passed}/{total} vectors passed")
