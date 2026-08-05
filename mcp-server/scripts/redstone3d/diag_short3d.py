"""diag_short3d.py — print the actual 3-D short pairs the audit finds, to
confirm they are real (two nets' conductors adjacent on the same layer) and to
see which structures they involve (cross vs tower vs stair)."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter, _PLANE_SHELL


def pairs(res, limit=15):
    owner = {}
    rep_face = {}
    for net, ws in res.wires.items():
        for p in ws:
            owner[p] = net
    for net, reps in res.repeaters.items():
        for (pos, f) in reps:
            owner[pos] = net; rep_face[pos] = f
    for p in res.torches:
        owner[p] = "TORCHES"
    for (pos, blk) in res.wall_torches:
        owner[pos] = "TORCHES"

    axis = BuildableRouter._REP_AXIS
    def couples(a, b, off):
        if a in rep_face and off not in axis[rep_face[a]]:
            return False
        boff = (-off[0], -off[1])
        if b in rep_face and boff not in axis[rep_face[b]]:
            return False
        return True

    out = []
    seen = set()
    for p, net in owner.items():
        x, y, z = p
        for dx, dz in _PLANE_SHELL:
            q = (x+dx, y, z+dz); o = owner.get(q)
            if o is not None and o != net and couples(p, q, (dx, dz)):
                k = tuple(sorted([p, q]))
                if k not in seen:
                    seen.add(k); out.append((p, q, net, o))
        for dy in (1, -1):
            q = (x, y+dy, z); o = owner.get(q)
            if o is not None and o != net:
                k = tuple(sorted([p, q]))
                if k not in seen:
                    seen.add(k); out.append((p, q, net, o))
    return out[:limit], len(seen)


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)
    res = r.route(verbose=False, max_rounds=6)
    ps, total = pairs(res)
    print(f"{mod}: {total} 3-D short pairs; first {len(ps)}:")
    for (a, b, na, nb) in ps:
        print(f"  {a} [{na}]  <->  {b} [{nb}]")


if __name__ == "__main__":
    main()
