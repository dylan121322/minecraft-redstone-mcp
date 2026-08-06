"""
diag_glass_impact.py — glass supports made the truth table worse (16/40 -> 10/40)
even though the isolated structure tests say only the DESCENT STAIRCASE needs a
powerable support (S2), while plain runs, tower tops and repeaters on supports are
all fine on glass (S1/S3/S4).

The staircase already emits its supports with role "block" (which stays stone), so
something else that needs power is being turned into glass. Compare the emitted
block at every support position between the stone build and the glass build, and
group the differences by what sits directly ABOVE them, to see which structures
actually changed material.
"""
import sys, os, json
from collections import Counter
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
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

    print(f"supports total: {len(res.supports)}")
    print(f"power_blocks (stay stone): {len(getattr(res, 'power_blocks', set()))}")
    passive = res.supports - getattr(res, "power_blocks", set())
    print(f"passive supports (become glass): {len(passive)}")

    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, {n: 1 for n in nl["inputs"]})

    # what sits directly above each passive support?
    above = Counter()
    for (x, y, z) in passive:
        s = rec.get((x, y + 1, z), "<empty>")
        tag = ("wire" if "wire" in s else "repeater" if "repeater" in s
               else "torch" if "torch" in s else "stone" if s.endswith("stone")
               else "glass" if "glass" in s else s)
        above[tag] += 1
    print(f"\nwhat sits directly above the glass supports:")
    for k, v in above.most_common():
        print(f"   {k}: {v}")

    # and what sits BESIDE them at the same level (a mount that needs power?)
    beside = Counter()
    for (x, y, z) in passive:
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            s = rec.get((x + dx, y, z + dz))
            if not s:
                continue
            tag = ("wire" if "wire" in s else "repeater" if "repeater" in s
                   else "torch" if "torch" in s else "stone"
                   if s.endswith("stone") else "glass" if "glass" in s else s)
            beside[tag] += 1
    print(f"\nwhat sits beside the glass supports (same level):")
    for k, v in beside.most_common():
        print(f"   {k}: {v}")

    # are any WALL TORCHES mounted on a passive support? those need power
    wt_bad = []
    for (q, blk) in res.wall_torches:
        # a wall torch's mount is the neighbour opposite its facing
        f = blk.split("facing=")[1].rstrip("]")
        d = {"west": (1, 0), "east": (-1, 0), "north": (0, 1),
             "south": (0, -1)}[f]
        mount = (q[0] + d[0], q[1], q[2] + d[1])
        if mount in passive:
            wt_bad.append((q, mount))
    print(f"\nWALL TORCHES whose mount became glass: {len(wt_bad)}")
    for q, m in wt_bad[:8]:
        print(f"   torch{q} mount{m}  <-- a wall torch cannot read a glass mount")

    # standing torches sitting ON a passive support
    st_bad = [p for p in res.torches if (p[0], p[1] - 1, p[2]) in passive]
    print(f"STANDING TORCHES on a glass block: {len(st_bad)}")
    for p in st_bad[:8]:
        print(f"   torch{p} sits on {(p[0], p[1]-1, p[2])}")


if __name__ == "__main__":
    main()
