"""
apply_solution.py — apply the enumerated bridge solution as a hard constraint:
reserve the solution's delivery voxels FIRST (so the y0 pass and other nets must
route around them), then route the rest, then judge the whole chip with MCHPRS.

This tests whether the conflict-free delivery assignment survives when the other
37 sinks and the source-to-bridge approaches are added.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ORTH, DIAG = coupling.ORTH, coupling.DIAG


def install_measured():
    def _foreign_plane(self, xz, net, owner):
        x, z = xz
        for dx, dz in ORTH:
            o = owner.get((x + dx, z + dz))
            if o is not None and o != net:
                return True
        for dx, dz in DIAG:
            o = owner.get((x + dx, z + dz))
            if o is None or o == net:
                continue
            if (x + dx, z) in owner or (x, z + dz) in owner:
                return True
        return False
    SH = [(dx, 0, dz) for dx, dz in ORTH] + [(0, 1, 0), (0, -1, 0)] + \
         [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    RB.BuildableRouter._foreign_plane = _foreign_plane
    RB.BuildableRouter._SHELL3D = SH


def main():
    sol = json.load(open(os.path.join(base, "alu1_bridge10_solution.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    install_measured()
    import importlib
    import placer, build_from_route
    importlib.reload(placer); importlib.reload(build_from_route)
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    y0 = pl.bounds[0][1]

    # reserve the solution's delivery voxels in owner3d BEFORE routing
    reserved = {}
    for s in sol["sinks"]:
        net = s["net"]; gx, gz = s["pin"]
        feed = (gx - 1, gz)
        if s["kind"] == "stair":
            cy = s["cy"]; dz = s["dz"]
            depth = cy + 1 - y0
            zz = gz + dz
            for i in range(1, depth + 1):
                yy = cy + 1 - i
                reserved[(gx - depth + i, yy, zz)] = f"{net}:sol"
            reserved[(gx - 1, y0, gz)] = f"{net}:sol"
        else:
            cy = s["cy"]
            cells, foot = down_tower_cells_dir(feed[0], feed[1], cy, y0,
                                               side=s["rot"][1], arm=s["rot"][0])
            for (x, y, z, b) in cells:
                if b == DUST or "torch" in b:
                    reserved[(x, y, z)] = f"{net}:sol"
            reserved[(feed[0], y0, feed[1])] = f"{net}:sol"
    print(f"reserved {len(reserved)} delivery voxels from the solution")

    # route with the reserved voxels claimed
    r = RB.BuildableRouter(pl, margin=16)
    for (x, y, z), own in reserved.items():
        r.owner3d[(x, y, z)] = own
    # let the router route; its checks see the reserved voxels as foreign
    res = r.route(verbose=False, max_rounds=rounds)

    # full 40-vector MCHPRS
    import nucleation as nuc
    from build_from_route import emit_blocks
    # emit: the reserved voxels are not in res, so add them manually as dust
    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_pos = pl.primary_outputs.get(nm(pb["y"][0]))
    c_pos = pl.primary_outputs.get(nm(pb["cout"][0]))
    ny = nc = both = 0
    yv_set = set(); cv_set = set()
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bv in (0, 1):
                for cin in (0, 1):
                    iv = {a_n: a, b_n: bv, cin_n: cin}
                    for i in range(4):
                        iv[op_n[i]] = (op >> i) & 1
                    for inet in nl["inputs"]:
                        iv.setdefault(inet, 0)
                    rec = {}
                    def setter(x, y, z, s):
                        if s == "minecraft:air":
                            rec.pop((x, y, z), None)
                        else:
                            rec[(x, y, z)] = s
                    emit_blocks(setter, pl, res, iv)
                    for (x, y, z) in reserved:
                        rec[(x, y, z)] = DUST
                    sc = nuc.Schematic.create("t")
                    for (x, y, z), s in rec.items():
                        sc.set_block_from_string(x, y, z, s)
                    w = nuc.MchprsWorld.create_with_options(sc, True, False)
                    w.tick(80)
                    yv = 1 if w.get_redstone_power(*y_pos) > 0 else 0
                    cv = 1 if w.get_redstone_power(*c_pos) > 0 else 0
                    yv_set.add(yv); cv_set.add(cv)
                    bb = (1 - bv) if op == 6 else bv
                    summ = a ^ bb ^ cin
                    cout = (a & bb) | (cin & (a ^ bb))
                    ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv,
                          6: summ}.get(op, 0)
                    ny += (yv == ey); nc += (cv == cout)
                    both += (yv == ey and cv == cout)
    print(f"FULL 40: both={both}/40 y={ny} c={nc} "
          f"y_stuck={len(yv_set)==1} c_stuck={len(cv_set)==1} "
          f"failed={len(res.failed)}")


if __name__ == "__main__":
    main()
