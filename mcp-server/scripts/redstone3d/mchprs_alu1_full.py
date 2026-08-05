"""
mchprs_alu1_full.py — build the fully-routed alu1 in MCHPRS and run its truth
table. This is the final arbiter: static checks disagreed about 45 "floating"
conductors (they are DOWN-tower wall torches, which attach sideways and need no
support), so instead of arguing about the predicate, simulate the real geometry.

Route: yield=(n18,n3,n6) under the measured coupling rule — 29/29 nets, 47/47
sinks fed, 0 interfering pairs.

alu1 is a 1-bit ALU slice: inputs a, b, cin, op[4]; outputs y, cout.
  op 0 -> AND, 1 -> OR, 2 -> ADD, 3 -> XOR, 6 -> SUB (b inverted)
Each vector rebuilds the world, injects the primary inputs as redstone_blocks at
the injector cells, ticks, and reads the two outputs.
"""
import sys, os, json, time
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import nucleation as nuc
import route_buildable as RB
import coupling
from build_from_route import emit_blocks

ORTH, DIAG = coupling.ORTH, coupling.DIAG
RB_BLOCK = "minecraft:redstone_block"


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
    mod = "alu1"
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n18+n3+n6").split("+"))
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    ticks = int(sys.argv[4]) if len(sys.argv) > 4 else 60

    install_measured()
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    nl = nls[mod]
    pl = place(nl, col_gap=16, row_gap=16)
    r = RB.BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in yields]
        tail = [n for n in nets if n in yields]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=rounds)
    print(f"[{mod}] yield={sorted(yields)} failed={len(res.failed)} "
          f"wires={res.total_wires()}")

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_n, cout_n = nm(pb["y"][0]), nm(pb["cout"][0])

    po = {}
    for net in nl["outputs"]:
        p = pl.primary_outputs.get(nm(pb[net][0]) if net in pb else net)
        if p:
            po[net] = p
    # primary_outputs maps net -> pos; resolve by net name directly
    y_pos = pl.primary_outputs.get(y_n)
    c_pos = pl.primary_outputs.get(cout_n)
    print(f"  PO y={y_n}@{y_pos}  cout={cout_n}@{c_pos}")
    if not y_pos or not c_pos:
        print("  cannot locate primary outputs; abort")
        return

    tests = []
    for op in (0, 1, 2, 3, 6):
        for a in (0, 1):
            for bb in (0, 1):
                for cin in (0, 1):
                    tests.append((a, bb, cin, op))

    ok = 0; total = 0
    t0 = time.time()
    for (a, bv, cin, op) in tests[:limit]:
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

        sc = nuc.Schematic.create(f"alu1_{op}_{a}{bv}{cin}")
        for (x, y, z), s in rec.items():
            sc.set_block_from_string(x, y, z, s)
        w = nuc.MchprsWorld.create_with_options(sc, True, False)
        w.tick(ticks)
        yv = 1 if w.get_redstone_power(*y_pos) > 0 else 0
        cv = 1 if w.get_redstone_power(*c_pos) > 0 else 0

        bb2 = (1 - bv) if op == 6 else bv
        summ = a ^ bb2 ^ cin
        cout = (a & bb2) | (cin & (a ^ bb2))
        ey = {0: a & bv, 1: a | bv, 2: summ, 3: a ^ bv, 6: summ}.get(op, 0)
        good = (yv == ey and cv == cout)
        ok += good; total += 1
        print(f"  op={op} a={a} b={bv} cin={cin}: y={yv}(e{ey}) "
              f"cout={cv}(e{cout}) {'OK' if good else 'X'}", flush=True)
    print(f"\nMCHPRS alu1: {ok}/{total}  ({time.time()-t0:.0f}s, {ticks} ticks)")


if __name__ == "__main__":
    main()
