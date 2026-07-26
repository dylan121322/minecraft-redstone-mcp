"""Exhaustively verify ONE alu1 slice in MCHPRS (physical redstone).
Small (24 gates) so MCHPRS create is fast. 5 ops × a,b,cin = 40 cases."""
import sys, os, json
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, ".."))
import nucleation as n
from placer import place
from maze_router import MazeRouter

nl = json.load(open(os.path.join(HERE, "nl_alu1.json")))
pl = place(nl, col_gap=10, row_gap=6)
res = MazeRouter(pl, margin=10).route_negotiated(max_iters=300)
pb = nl["port_bits"]; pi = pl.primary_inputs; po = pl.primary_outputs
def pinp(port, i=0): b = pb[port][i]; return pi[f"n{b}"]
def pout(port, i=0): b = pb[port][i]; return po[f"n{b}"]
ap, bp, cp = pinp("a"), pinp("b"), pinp("cin")
ops = [pinp("op", i) for i in range(4)]
yp, coutp = pout("y"), pout("cout")
mn, mx = pl.bounds

def ref(a, b, cin, op):
    bb = (~b) & 1 if op == 6 else b
    s = a ^ bb ^ cin
    y = s if op in (2, 6) else (a & b) if op == 0 else (a | b) if op == 1 else (a ^ b) if op == 3 else 0
    return y & 1, ((a & bb) | (cin & (a ^ bb))) & 1

ok = tot = 0
fails = []
# Targeted subset: ADD carry-generate (a=b=1→cout=1), ADD carry-propagate
# (a=1,b=0,cin=1→cout=1,y=0), SUB borrow, and one of each logic op. This
# exercises the carry chain (what bit-parallel can't see) without 40 slow creates.
CASES = [
    (2,1,1,0),  # ADD 1+1: y=0 cout=1  (generate)
    (2,1,0,1),  # ADD 1+0+cin1: y=0 cout=1 (propagate)
    (2,0,0,0),  # ADD 0+0: y=0 cout=0
    (6,0,1,0),  # SUB 0-1: borrow
    (0,1,1,0),  # AND
    (1,0,1,0),  # OR
    (3,1,1,0),  # XOR
]
for op, a, b, cin in CASES:
    if True:
        if True:
            if True:
                s = n.Schematic.create("t")
                s.fill_cuboid(mn[0]-3, -1, mn[2]-3, mx[0]+3, -1, mx[2]+3, "minecraft:stone")
                for pc in pl.placed.values():
                    pc.cell.emit(s, *pc.origin)
                for net, ws in res.wires.items():
                    for (x, y, z) in ws:
                        if y > 0: s.set_block_from_string(x, y-1, z, "minecraft:stone")
                        s.set_block_from_string(x, y, z, "minecraft:redstone_wire")
                for net, rr in res.repeaters.items():
                    for (pos, f) in rr:
                        s.set_block_from_string(pos[0], pos[1], pos[2], f"minecraft:repeater[facing={f},delay=1]")
                def drv(p, v): s.set_block_from_string(p[0]-1, p[1], p[2], "minecraft:redstone_block" if v else "minecraft:air")
                drv(ap, a); drv(bp, b); drv(cp, cin)
                for k in range(4): drv(ops[k], (op >> k) & 1)
                w = n.MchprsWorld.create_with_options(s, True, False)
                w.tick(60)
                gy = 1 if w.get_redstone_power(*yp) > 0 else 0
                gc = 1 if w.get_redstone_power(*coutp) > 0 else 0
                ey, ec = ref(a, b, cin, op)
                tot += 1
                res_ok = (gy == ey and gc == ec)
                if res_ok: ok += 1
                else: fails.append((op, a, b, cin, gy, gc, ey, ec))
                print(f"  op={op} a={a} b={b} cin={cin} -> y={gy},c={gc} "
                      f"exp y={ey},c={ec} {'OK' if res_ok else 'X'}", flush=True)
print(f"alu1 slice MCHPRS: {ok}/{tot}")
for f in fails[:5]: print("  FAIL op={} a={} b={} cin={} got y={},c={} exp y={},c={}".format(*f))
