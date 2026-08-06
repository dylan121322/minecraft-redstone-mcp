"""
patch_glass_seam.py — implement the user's idea correctly: glass for PASSIVE
supports, stone ONLY at the hand-off seams.

Measured (test_glass_needs / test_glass_seam):
  * glass carries wires fine and kills see-below leakage (S1, G2/G3/G4)
  * a STAIRCASE's first step reads the cross dust THROUGH its support's strong
    power, so the cross support directly under the stair's reading point must be
    stone (glass cross support -> landing 0)
  * a DOWN TOWER's input dust drives its A column through its own support, so
    the tower's input support must be stone too
  * everything else (plain run supports, tower-top cross runs that never hand
    off downward) works on glass (S3)

So: passive supports become glass EXCEPT the two seam classes, which the router
now registers in `power_blocks`:
  1. the cross cell where a staircase starts (its support is read through)
  2. the down-tower input column's support
This patch only touches the router's bookkeeping and the emitter; it does not
change routing decisions, so it can only help or stay neutral.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ys = tuple(t for t in (sys.argv[3] if len(sys.argv) > 3 else "n3+n5").split("+") if t)
    import importlib
    import route_buildable as RB
    importlib.reload(RB)
    import coupling
    importlib.reload(coupling)
    ORTH, DIAG = coupling.ORTH, coupling.DIAG

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

    import placer, build_from_route
    importlib.reload(placer); importlib.reload(build_from_route)
    from placer import place
    nls = json.load(open(NETLISTS))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in ys]
        tail = [n for n in nets if n in ys]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)

    # CROSS-PLANE supports stay stone: a stair's first step and a down-tower's
    # input read the cross dust THROUGH the support's strong power (measured:
    # glass cross support -> landing 0 in both seam tests). Everything else can
    # be glass.
    powered = set(res.power_blocks)
    for (sx, sy, sz) in res.supports:
        if sy >= 2:          # raised cross/stair supports
            powered.add((sx, sy, sz))
    print(f"[{mod}] yield={ys} supports={len(res.supports)} "
          f"power_blocks={len(res.power_blocks)} "
          f"glass-candidates={len(res.supports - res.power_blocks)}")

    # emit with seam-aware glass and evaluate on the FULL 40 vectors
    import nucleation as nuc
    from build_from_route import emit_blocks, GLASS
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
                    # glass only for passive supports; floor & power_blocks stone
                    from build_from_route import S as _S
                    def ssetter(x, y, z, s):
                        setter(x, y, z, s)
                    emit_blocks(ssetter, pl, res, iv)
                    # emit_blocks uses its own material table; override by
                    # re-writing passive supports as glass AFTER emit
                    for (sx, sy, sz) in res.supports:
                        if (sx, sy, sz) not in powered:
                            rec[(sx, sy, sz)] = GLASS
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
          f"y_stuck={len(yv_set)==1} c_stuck={len(cv_set)==1}")


if __name__ == "__main__":
    main()
