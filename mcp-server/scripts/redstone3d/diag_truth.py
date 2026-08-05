"""
diag_truth.py — the MCHPRS-driven sweep plateaus at 4/10 with zero shorts, so the
remaining error is systematic, not a routing-order problem. Show WHICH outputs are
wrong and in what pattern:

  * per vector: expected vs measured y and cout
  * is y stuck (always the same regardless of inputs)?
  * does cout track the adder correctly?
  * for the failing output, which net drives it and is that net fully connected?

A stuck output means its driving gate sees a floating input; a wrong-but-moving
output means a logic/parity error (e.g. an inverting via).
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
import route_buildable as RB
import coupling
from build_from_route import emit_blocks

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
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n8").split("+"))
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ticks = int(sys.argv[3]) if len(sys.argv) > 3 else 80
    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls["alu1"]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yields]
        tail = [n for n in nets if n in yields]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)
    print(f"yield={sorted(yields)} failed={res.failed} wires={res.total_wires()}")

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_net, c_net = nm(pb["y"][0]), nm(pb["cout"][0])
    y_pos = pl.primary_outputs[y_net]; c_pos = pl.primary_outputs[c_net]
    print(f"y={y_net}@{y_pos}  cout={c_net}@{c_pos}")
    print(f"y net failed?    {y_net in res.failed}")
    print(f"cout net failed? {c_net in res.failed}")

    ys_seen = set(); cs_seen = set()
    rows = []
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
                    sc = nuc.Schematic.create("d")
                    for (x, y, z), s in rec.items():
                        sc.set_block_from_string(x, y, z, s)
                    w = nuc.MchprsWorld.create_with_options(sc, True, False)
                    w.tick(ticks)
                    yv = 1 if w.get_redstone_power(*y_pos) > 0 else 0
                    cv = 1 if w.get_redstone_power(*c_pos) > 0 else 0
                    bb = (1 - bv) if op == 6 else bv
                    summ = a ^ bb ^ cin
                    cout = (a & bb) | (cin & (a ^ bb))
                    ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv,
                          6: summ}.get(op, 0)
                    ys_seen.add(yv); cs_seen.add(cv)
                    rows.append((op, a, bv, cin, yv, ey, cv, cout))
    print(f"\n{'op':>3s} {'a':>1s} {'b':>1s} {'ci':>2s} | "
          f"{'y':>1s} {'ey':>2s} {'ok':>2s} | {'c':>1s} {'ec':>2s} {'ok':>2s}")
    ny = nc = 0
    for (op, a, bv, cin, yv, ey, cv, cout) in rows:
        oky = "OK" if yv == ey else "X"
        okc = "OK" if cv == cout else "X"
        ny += (yv == ey); nc += (cv == cout)
        print(f"{op:3d} {a:1d} {bv:1d} {cin:2d} | {yv:1d} {ey:2d} {oky:>2s} "
              f"| {cv:1d} {cout:2d} {okc:>2s}")
    print(f"\ny correct: {ny}/{len(rows)}   cout correct: {nc}/{len(rows)}")
    print(f"y values observed: {sorted(ys_seen)}  "
          f"{'STUCK' if len(ys_seen) == 1 else 'moving'}")
    print(f"cout values observed: {sorted(cs_seen)}  "
          f"{'STUCK' if len(cs_seen) == 1 else 'moving'}")
    both = sum(1 for r in rows if r[4] == r[5] and r[6] == r[7])
    print(f"both correct: {both}/{len(rows)}")


if __name__ == "__main__":
    main()
