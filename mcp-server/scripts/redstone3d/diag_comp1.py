"""
diag_comp1.py — the dominant failure is not "the last cell did not connect" but
"the route never connects to its SOURCE at all":

    net   voxels  connected-to-source
    n4      299        1
    n27     109        1
    n18      92        1
    n11      59        1
    ...

Seven nets look like this. So the break is at the very first step out of the
source. Dump the source neighbourhood: what the placer says the source is, what
the router owns near it, and what emit actually writes — including the out_stub
that is supposed to join a gate's real output pin to the published source.
"""
import sys, os, json
from collections import deque
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import route_buildable as RB
import coupling
from build_from_route import emit_blocks

ORTH, DIAG = coupling.ORTH, coupling.DIAG
CONN = ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0),
        (1, 1, 0), (-1, 1, 0), (0, 1, 1), (0, 1, -1),
        (1, -1, 0), (-1, -1, 0), (0, -1, 1), (0, -1, -1))


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
    net = sys.argv[1] if len(sys.argv) > 1 else "n4"
    yields = set((sys.argv[2] if len(sys.argv) > 2 else "n13+n14+n8").split("+"))
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

    src = pl.net_sources[net]
    vox = set(res.wires.get(net, ())) | {p for (p, _f) in res.repeaters.get(net, ())}
    print(f"{net}: source={src}  voxels={len(vox)}")
    is_pi = net in pl.primary_inputs
    print(f"  is primary input: {is_pi}")
    stub = [(a, b) for (a, b) in pl.out_stubs if tuple(b) == tuple(src)]
    print(f"  out_stub (real pin -> published source): {stub}")

    # what does the net own adjacent to the source?
    adj = [v for v in vox
           if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
    print(f"  net voxels orthogonally adjacent to source: {adj}")
    near = sorted(v for v in vox
                  if abs(v[0]-src[0]) <= 3 and abs(v[2]-src[2]) <= 3)
    print(f"  net voxels within 3 cells: {near[:12]}")

    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 1 for n in nl["inputs"]})

    print(f"\n  EMITTED blocks around the source (y=0..2):")
    for dy in (2, 1, 0):
        for dz in (-1, 0, 1):
            row = []
            for dx in (-2, -1, 0, 1, 2, 3):
                q = (src[0]+dx, src[1]+dy, src[2]+dz)
                s = rec.get(q)
                if not s:
                    row.append("    .")
                    continue
                t = ("wire" if "wire" in s else "rep" if "repeater" in s
                     else "torch" if "torch" in s else "stone"
                     if s.endswith("stone") else "?")
                own = "*" if q in vox else " "
                row.append(f"{t:>4s}{own}")
            print(f"    dy={dy:+d} dz={dz:+d}: " + " ".join(row))
    print("    (* = this net owns the voxel)")

    # the component actually reached
    frontier = [v for v in vox
                if abs(v[0]-src[0]) + abs(v[1]-src[1]) + abs(v[2]-src[2]) == 1]
    comp = set(frontier); dq = deque(frontier)
    while dq:
        cur = dq.popleft()
        for d in CONN:
            q = (cur[0]+d[0], cur[1]+d[1], cur[2]+d[2])
            if q in vox and q not in comp:
                comp.add(q); dq.append(q)
    print(f"\n  reachable component from source: {len(comp)} of {len(vox)}")
    print(f"  component cells: {sorted(comp)[:10]}")
    orphan = sorted(vox - comp)
    print(f"  ORPHANED voxels: {len(orphan)} e.g. {orphan[:10]}")


if __name__ == "__main__":
    main()
