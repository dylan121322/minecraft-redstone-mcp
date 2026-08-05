"""
audit_shorts3d.py — REVIEW FINDING #3 VERIFICATION.

_count_shorts() builds its owner map from wire_owner, which _materialize fills
ONLY with y0 wires and repeaters. Cross-plane dust, staircase rungs, tower
torches and wall torches are invisible to it, so "shorts=0" only certifies the
y=0 plane. This audit rebuilds the owner from EVERYTHING (all wires at any y,
repeaters, standing torches, wall torches) and recounts under the true coupling
rules (same-layer 8-neighbourhood + directly above/below + repeater front/back
axis). Any difference is a short the router's own metric misses.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter, _PLANE_SHELL


def audit(res):
    owner = {}
    rep_face = {}
    for net, ws in res.wires.items():
        for p in ws:
            owner[p] = net
    for net, reps in res.repeaters.items():
        for (pos, f) in reps:
            owner[pos] = net; rep_face[pos] = f
    # Torches carry their NET since review finding #4 was fixed, so same-net
    # rung-vs-wire adjacency is correctly NOT a short, while two different nets'
    # towers are correctly flagged.
    for p in res.torches:
        owner[p] = res.torch_nets.get(p, "?")
    for (pos, blk) in res.wall_torches:
        owner[pos] = res.wall_torch_nets.get(pos, "?")

    def couples(a, b, off):
        axis = BuildableRouter._REP_AXIS
        if a in rep_face and off not in axis[rep_face[a]]:
            return False
        boff = (-off[0], -off[1])
        if b in rep_face and boff not in axis[rep_face[b]]:
            return False
        return True

    seen = set()
    for p, net in owner.items():
        x, y, z = p
        for dx, dz in _PLANE_SHELL:
            q = (x+dx, y, z+dz); o = owner.get(q)
            if o is not None and o != net and couples(p, q, (dx, dz)):
                k = tuple(sorted([p, q]))
                if k not in seen:
                    seen.add(k)
        for dy in (1, -1):
            q = (x, y+dy, z); o = owner.get(q)
            if o is not None and o != net:
                k = tuple(sorted([p, q]))
                if k not in seen:
                    seen.add(k)
    return len(seen)


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mods = sys.argv[1:] if len(sys.argv) > 1 else ["alu1", "Control"]
    for mod in mods:
        pl = place(nls[mod], col_gap=16, row_gap=16)
        r = BuildableRouter(pl, margin=16)
        res = r.route(verbose=False, max_rounds=6)
        plane_shorts, _ = r._count_shorts(res)
        full_shorts = audit(res)
        flag = "  <-- MISMATCH" if full_shorts != plane_shorts else ""
        print(f"{mod}: y0-only={plane_shorts}  full-3d={full_shorts}{flag}")
        # what layers have conductors?
        from collections import Counter
        ys = Counter(p[1] for p in owner_keys(res))
        if len(ys) > 1:
            print(f"   conductor layers: {dict(sorted(ys.items()))}")


def owner_keys(res):
    for net, ws in res.wires.items():
        for p in ws:
            yield p
    for net, reps in res.repeaters.items():
        for (pos, f) in reps:
            yield pos
    for p in res.torches:
        yield p
    for (pos, blk) in res.wall_torches:
        yield pos


if __name__ == "__main__":
    main()
