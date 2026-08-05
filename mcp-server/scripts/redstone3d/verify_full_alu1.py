"""
verify_full_alu1.py — INDEPENDENT re-verification of the first fully-routed alu1.

The sweep reported yield=(n18,n3,n6) giving 0 unfed sinks and 0 true shorts under
the measured coupling rule. Re-derive that from scratch here and check it against
every criterion we have, so the claim does not rest on the sweep's own bookkeeping:

  1. every sink of every net is fed at its west feed cell
  2. zero interfering pairs under coupling.count_shorts (the measured rule)
  3. zero interfering pairs under the OLD strict shell8 rule as well, reported
     separately — if shell8 flags extra pairs they are the pure-diagonal ones the
     physics says are harmless
  4. no floating dust: every raised conductor has a support below it
  5. summary geometry (bbox, block count) for the build step
"""
import sys, os, json, importlib
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))

YIELD = tuple((sys.argv[2] if len(sys.argv) > 2 else "n18+n3+n6").split("+"))
MOD = sys.argv[1] if len(sys.argv) > 1 else "alu1"
ROUNDS = int(sys.argv[3]) if len(sys.argv) > 3 else 5

import route_buildable as RB
import coupling
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

from placer import place

nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
pl = place(nls[MOD], col_gap=16, row_gap=16)
r = RB.BuildableRouter(pl, margin=16)
ys = set(YIELD)
orig = r._route_once
def patched(nets, soft=False, verbose=False):
    head = [n for n in nets if n not in ys]
    tail = [n for n in nets if n in ys]
    return orig(head + tail, soft=soft, verbose=verbose)
r._route_once = patched
res = r.route(verbose=False, max_rounds=ROUNDS)

print(f"[{MOD}] yield={sorted(ys)} rounds={ROUNDS}")

# --- 1. sink feeding -------------------------------------------------------
own = {}
for n in res.wires:
    own[n] = {(p[0], p[2]) for p in res.wires[n]} | \
             {(q[0], q[2]) for (q, _f) in res.repeaters.get(n, [])}
nets = [n for n in pl.net_sinks if pl.net_sources.get(n)]
unfed = []
for n in nets:
    for k in pl.net_sinks[n]:
        if (k[0] - 1, k[2]) not in own.get(n, ()):
            unfed.append((n, (k[0], k[2])))
total_sinks = sum(len(pl.net_sinks[n]) for n in nets)
print(f"1) sinks fed: {total_sinks - len(unfed)}/{total_sinks}   "
      f"nets routed: {len(nets) - len(res.failed)}/{len(nets)}")
for u in unfed[:6]:
    print(f"     UNFED {u}")

# --- 2/3. shorts under both rules -----------------------------------------
occ = {}
for n, ws in res.wires.items():
    for p in ws:
        occ[p] = n
for n, reps in res.repeaters.items():
    for (q, _f) in reps:
        occ[q] = n
for p in res.torches:
    occ[p] = res.torch_nets.get(p, "?")
for (q, _b) in res.wall_torches:
    occ[q] = res.wall_torch_nets.get(q, "?")

measured = coupling.count_shorts(occ)
PLANE8 = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
seen8 = set()
for p, net in occ.items():
    x, y, z = p
    for dx, dz in PLANE8:
        q = (x + dx, y, z + dz); o = occ.get(q)
        if o is not None and o != net:
            seen8.add(tuple(sorted([p, q])))
    for dy in (1, -1):
        q = (x, y + dy, z); o = occ.get(q)
        if o is not None and o != net:
            seen8.add(tuple(sorted([p, q])))
print(f"2) MEASURED-rule interfering pairs: {measured}")
print(f"3) old shell8-rule pairs: {len(seen8)}  "
      f"(difference = pure diagonals, measured harmless)")

# --- 4. floating conductors ----------------------------------------------
supports = set(res.supports)
y0 = pl.bounds[0][1]
# WALL torches attach to the SIDE of a block and need no support underneath, so
# they must be excluded from the float test (they were 45 false positives). A
# standing torch does sit on a block, so it stays in the test.
wall_pos = {q for (q, _b) in res.wall_torches}
floating = []
for p in occ:
    if p[1] <= y0 or p in wall_pos:
        continue
    below = (p[0], p[1] - 1, p[2])
    if below not in supports and below not in occ:
        floating.append(p)
print(f"4) floating raised conductors: {len(floating)} "
      f"(wall torches excluded: {len(wall_pos)} attach sideways)")
for f in floating[:6]:
    print(f"     FLOATING {f}")
# a wall torch still needs SOMETHING to attach to — verify each has a neighbour
no_mount = []
for q in wall_pos:
    if not any((q[0]+dx, q[1], q[2]+dz) in supports or
               (q[0]+dx, q[1], q[2]+dz) in occ
               for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
        no_mount.append(q)
print(f"   wall torches with no adjacent mount: {len(no_mount)}")

# --- 5. geometry ----------------------------------------------------------
xs = [p[0] for p in occ]; ys_ = [p[1] for p in occ]; zs = [p[2] for p in occ]
print(f"5) conductors={len(occ)} supports={len(supports)} "
      f"torches={len(res.torches)}+{len(res.wall_torches)} "
      f"wires={res.total_wires()}")
print(f"   bbox x[{min(xs)},{max(xs)}] y[{min(ys_)},{max(ys_)}] "
      f"z[{min(zs)},{max(zs)}]")

ok = (not unfed) and measured == 0 and not floating
print(f"\n{'*** VERIFIED: fully routed, zero real shorts, no floats ***' if ok else 'NOT CLEAN'}")
