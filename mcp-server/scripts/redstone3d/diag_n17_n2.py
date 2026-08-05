"""
diag_n17_n2.py — the last unfed sink is n2@(174,19); n17 blocks all 28 of its
candidates even though n17 is already routed LAST (it is in the yield set). So
n17 is not merely "in the way by accident" — its own pins force it through that
area. Print both nets' pin geometry and the exact cells of n17 that sit inside
n2's candidate footprints, to decide between:

  (a) the two sinks are simply too close  -> placement must separate them
  (b) n17 takes a detour through the area -> a better n17 route frees it
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter
from via_gadget import down_tower_cells_dir

DUST = "minecraft:redstone_wire"
ROTS = (((0, 1), (-1, 0)), ((0, -1), (-1, 0)),
        ((-1, 0), (0, 1)), ((-1, 0), (0, -1)))
SHELL = [(dx, 0, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1)
         if (dx, dz) != (0, 0)] + [(0, 1, 0), (0, -1, 0)]


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    ys = {"n13", "n17", "n7", "n8"}
    pl = place(nls["alu1"], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    orig = r._route_once
    def patched(nets, soft=False, verbose=False):
        head = [n for n in nets if n not in ys]
        tail = [n for n in nets if n in ys]
        return orig(head + tail, soft=soft, verbose=verbose)
    r._route_once = patched
    res = r.route(verbose=False, max_rounds=6)
    y0 = pl.bounds[0][1]

    print("n2  source:", pl.net_sources["n2"], " sinks:", pl.net_sinks["n2"])
    print("n17 source:", pl.net_sources["n17"], " sinks:", pl.net_sinks["n17"])

    # n17's conductors near n2's last sink
    gx, gz = 174, 19
    feed = (gx - 1, gz)
    n17 = {p for p in res.wires.get("n17", ())}
    for (q, _f) in res.repeaters.get("n17", ()):
        n17.add(q)
    near = sorted(p for p in n17
                  if abs(p[0] - feed[0]) <= 6 and abs(p[2] - feed[1]) <= 6)
    print(f"\nn17 conductors within 6 cells of n2's feed {feed}: {len(near)}")
    for p in near[:24]:
        print(f"   {p}")

    # which of n2's candidate voxels do they hit?
    print(f"\nn2 candidate footprints vs n17 (cy=4 as example):")
    for arm, side in ROTS:
        cells, foot = down_tower_cells_dir(feed[0], feed[1], y0 + 4, y0,
                                           side=side, arm=arm)
        cond = [(x, y, z) for (x, y, z, b) in cells
                if b == DUST or "torch" in b]
        clash = []
        for v in cond:
            if v in n17:
                clash.append((v, "on"))
            else:
                for dx, dy, dz in SHELL:
                    if (v[0]+dx, v[1]+dy, v[2]+dz) in n17:
                        clash.append((v, "adj"))
                        break
        print(f"   rot arm={arm} side={side}: footprint={sorted(foot)} "
              f"clashes={len(clash)}")
        for c in clash[:4]:
            print(f"      {c[0]} {c[1]}")

    # is n17 even fed? (it is in the yield set, so it routes last)
    own17 = {(p[0], p[2]) for p in res.wires.get("n17", ())} | \
            {(q[0], q[2]) for (q, _f) in res.repeaters.get("n17", ())}
    for k in pl.net_sinks["n17"]:
        print(f"\nn17 sink {k}: fed={(k[0]-1, k[2]) in own17}")


if __name__ == "__main__":
    main()
