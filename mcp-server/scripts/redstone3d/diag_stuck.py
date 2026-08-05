"""
diag_stuck.py — MCHPRS says the fully-routed alu1 is stuck-high (y and cout are 1
for every input). Routing is complete (29/29 nets, 0 interfering pairs) and the
static checks pass, so the fault is electrical. Trace it:

  1. is the PI injection even energising the PI cell?
  2. for one PI net, walk its own conductors from the source and find where the
     power stops
  3. at the first dead cell, dump the neighbourhood so the broken join is visible

Build ONE world (all PIs driven to 1) and probe, rather than running vectors.
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
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


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
    yields = set((sys.argv[1] if len(sys.argv) > 1 else "n18+n3+n6").split("+"))
    focus = sys.argv[2] if len(sys.argv) > 2 else None
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
    res = r.route(verbose=False, max_rounds=5)

    iv = {n: 1 for n in nl["inputs"]}          # drive every PI to 1
    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, iv)
    sc = nuc.Schematic.create("stuck")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)

    print(f"built {len(rec)} blocks, ticked {ticks}")
    print("\n1) PI injection check (all driven to 1):")
    for net, pos in sorted(pl.primary_inputs.items()):
        inj = (pos[0] - 1, pos[1], pos[2])
        print(f"   {net:5s} injector{inj}={rec.get(inj,'-').replace('minecraft:','')[:14]:14s} "
              f"pow={w.get_redstone_power(*inj):2d}   "
              f"PI cell{tuple(pos)}={rec.get(tuple(pos),'-').replace('minecraft:','')[:14]:14s} "
              f"pow={w.get_redstone_power(*pos)}")

    nets = [n for n in pl.net_sinks if pl.net_sources.get(n)]
    targets = [focus] if focus else [n for n in pl.primary_inputs][:3]
    for net in targets:
        if net not in res.wires:
            continue
        print(f"\n2) walking {net} from its source")
        s = pl.net_sources[net]
        cells = {(p[0], p[2]): p for p in res.wires[net] if p[1] == pl.bounds[0][1]}
        reps = {(q[0], q[2]): q for (q, _f) in res.repeaters.get(net, [])}
        allc = dict(cells); allc.update(reps)
        start = (s[0], s[2])
        seen = {start}; q = deque([start]); dead = []
        n_live = 0
        while q:
            cur = q.popleft()
            p3 = allc.get(cur)
            if p3:
                pw = w.get_redstone_power(*p3)
                if pw > 0:
                    n_live += 1
                elif len(dead) < 8:
                    dead.append((p3, pw))
            for dx, dz in _H:
                nx = (cur[0] + dx, cur[1] + dz)
                if nx in seen or nx not in allc:
                    continue
                seen.add(nx); q.append(nx)
        print(f"   own y0 cells reached={len(seen)} live={n_live} "
              f"first dead: {dead[:5]}")
        for k in pl.net_sinks[net]:
            feed = (k[0] - 1, pl.bounds[0][1], k[2])
            print(f"   sink {k}: feed{feed} "
                  f"blk={rec.get(feed,'-').replace('minecraft:','')[:16]:16s} "
                  f"pow={w.get_redstone_power(*feed)}  "
                  f"pin={rec.get((k[0],k[1],k[2]),'-').replace('minecraft:','')[:20]}")


if __name__ == "__main__":
    main()
