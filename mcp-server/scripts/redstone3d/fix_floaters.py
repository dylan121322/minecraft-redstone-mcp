"""
fix_floaters.py — local jog repair for a saved solution: for every floating
plane wire (its support cell hosts a conductor — in-game the wire pops), jog
the run ONE cell sideways (z±1, then x±1) and re-validate the couplings of
the new cells against the full occupancy. The router stays untouched; this is
a placement-level post-pass on the few (4-11) cells the negotiation missed.

usage: python3 fix_floaters.py [in.json] [out.json]
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "riscv_synth"))
import route_buildable as RB
import coupling
from placer import place
from build_from_route import emit_blocks

NETLISTS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "..", "riscv_synth", "netlists.json")


def _load_netlists():
    return json.load(open(NETLISTS))


def main():
    fin = sys.argv[1] if len(sys.argv) > 1 else "alu1_solution_40of40.json"
    fout = sys.argv[2] if len(sys.argv) > 2 else "alu1_solution_fixed.json"
    dump = json.load(open(fin))
    placements = dump["placements"]
    mod = dump.get("mod", "alu1")
    nls = _load_netlists()
    nl = nls[mod]
    pl = place(nl, col_gap=dump.get("col_gap", 16), row_gap=16)

    SOLID = {"minecraft:stone", "minecraft:glass", "minecraft:target"}

    def materialize(placements):
        r = RB.BuildableRouter(pl, margin=16)
        res = r._materialize(list(placements.keys()), placements, {})
        return r, res

    def full_occ(res):
        occ = {}
        for n, ws in res.wires.items():
            for p in ws:
                occ[p] = n
        for n, reps in res.repeaters.items():
            for (q, _f) in reps:
                occ[q] = n
        return occ

    def floater_cells(res):
        """wires whose support cell is another wire/repeater (would pop)."""
        occ = full_occ(res)
        need = set()
        for n, ws in res.wires.items():
            for (x, y, z) in ws:
                sup = (x, y - 1, z)
                if sup in occ:
                    need.add((x, y, z))
        return need

    def couplings_ok(res, cells, net):
        """new cells must not couple with any foreign conductor."""
        occ = full_occ(res)
        for c in cells:
            for dx, dy, dz in coupling.shell_offsets():
                q = (c[0] + dx, c[1] + dy, c[2] + dz)
                o = occ.get(q)
                if o is not None and o != net:
                    if coupling.couples(c, q, occ):
                        return False
        return True

    r, res = materialize(placements)
    floaters = floater_cells(res)
    print(f"floaters: {len(floaters)}")
    for f in sorted(floaters):
        print("  ", f)

    # for each floater, jog the owning net's run
    for (fx, fy, fz) in sorted(floaters):
        # find the owning net and its run neighbours
        owner = None
        for n, ws in res.wires.items():
            if (fx, fy, fz) in ws:
                owner = n
                break
        if owner is None:
            print(f"  no owner for {fx,fy,fz}?")
            continue
        ps = placements[owner]
        dust = {(p[1], p[2], p[3]) for p in ps if p[0] == "dust"}
        # run direction: look at +/-x and +/-z neighbours
        runs = []
        for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (fx + d[0], fy, fz + d[1]) in dust:
                runs.append(d)
        print(f"  floater {fx,fy,fz} net={owner} runs={runs}")
        fixed = False
        # try jogs along the run's transverse direction
        for jd in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            if not runs:
                break
            jx, jz = jd
            # new cells: the floater moves to (fx+jx, fy, fz+jz); the two
            # neighbours connect through it — need the L-path cells too
            new_cells = []
            ok = True
            # build the 5-cell jog: run comes along runs[0] and leaves along
            # (runs[0] or runs[1]); simplest: move the floater and add the two
            # elbow cells so neighbours still connect orthogonally
            moved = (fx + jx, fy, fz + jz)
            elbows = []
            for d in runs[:2]:
                nx, nz = fx + d[0], fz + d[1]
                elbows.append((nx, fy, nz))  # elbow cell = neighbour column, jog row
            # elbow cells: neighbour (nx, fz) -> elbow (nx, fz+jz?) -> moved -> ...
            # simpler canonical jog: replace the single cell with a 3-cell
            # detour: (fx-1, z) -> (fx-1, z+j) -> (fx, z+j) -> (fx+1, z+j) -> (fx+1, z)
            # we only ADD the cells that are not already in the run
            cand = set()
            if (1, 0) in runs or (-1, 0) in runs:
                # run along x: jog along z
                z2 = fz + jz if jd in ((0, 1), (0, -1)) else fz + (1 if fz % 2 == 0 else -1)
                cand = {(fx - 1, fy, z2), (fx, fy, z2), (fx + 1, fy, z2)}
                rem = {(fx, fy, fz)}
            else:
                # run along z: jog along x
                x2 = fx + jx if jd in ((1, 0), (-1, 0)) else fx + 1
                cand = {(x2, fy, fz - 1), (x2, fy, fz), (x2, fy, fz + 1)}
                rem = {(fx, fy, fz)}
            # candidate cells must not belong to a FOREIGN net; same-net cells
            # may stay (the jog merges into the existing run). New cells'
            # supports must be free of conductors, and no new couplings.
            occ = full_occ(res)
            new_cells = []
            for c in cand:
                o = occ.get(c)
                if o is not None and o != owner:
                    ok = False
                    break
                if o is None:
                    new_cells.append(c)
                    sup = (c[0], c[1] - 1, c[2])
                    if sup in occ:
                        ok = False
                        break
            if not ok:
                continue
            if new_cells and not couplings_ok(res, new_cells, owner):
                continue
            # apply: remove floater dust, add NEW jog cells + supports
            ps2 = []
            for p in ps:
                if p[0] == "dust" and (p[1], p[2], p[3]) == (fx, fy, fz):
                    continue
                ps2.append(p)
            for c in new_cells:
                ps2.append(["dust", c[0], c[1], c[2]])
                if c[1] > 0:
                    ps2.append(["support", c[0], c[1] - 1, c[2]])
            placements[owner] = ps2
            fixed = True
            print(f"    jogged via {cand}")
            break
        if not fixed:
            print(f"    COULD NOT FIX {fx,fy,fz}")

    # re-materialize + re-audit
    r, res = materialize(placements)
    left = floater_cells(res)
    print(f"remaining floaters: {len(left)}")
    for f in sorted(left):
        print("  ", f)
    dump["placements"] = placements
    with open(fout, "w") as fh:
        json.dump(dump, fh)
    print(f"saved -> {fout}")


if __name__ == "__main__":
    main()
