"""
diag_loaded.py — diagnose the SAVED placements (last_placements.json) without
re-routing. The 40-minute stochastic route is run ONCE (pathfinder3d_eval.py
persists it); this tool re-materializes that exact world for chosen vectors
and dumps:

  * per-net source power vs logic expectation (level-ordered, mismatch-flagged)
  * per-gate input feed powers and output pin power vs expectation
  * the y/c output paths: stub repeater, pin, source dust, and every foreign
    conductor inside the coupling shell (who powers the output when it should
    be dark)
  * a 2-D power map around any gate passed on the command line

usage: python diag_loaded.py [placements.json] [op,a,b,cin] [op,a,b,cin] ...
"""
import sys, os, json
from collections import defaultdict
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base)
sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
import coupling
import route_buildable as RB
from placer import place
from build_from_route import emit_blocks
import nucleation as nuc

NETLISTS = os.path.join(base, "..", "riscv_synth", "netlists.json")


def logic_sim(nl, iv):
    vals = {n: int(v) for n, v in iv.items()}
    changed = True
    for _ in range(50):
        if not changed:
            break
        changed = False
        for cname, cdata in nl["cells"].items():
            gtype = cdata["type"]
            ins = [vals.get(net, 0) for net in cdata["inputs"].values()]
            if gtype == "NOT":
                out = 1 - ins[0]
            elif gtype == "AND":
                out = 1 if all(ins) else 0
            elif gtype == "OR":
                out = 1 if any(ins) else 0
            elif gtype == "NAND":
                out = 0 if all(ins) else 1
            elif gtype == "NOR":
                out = 1 if not any(ins) else 0
            else:
                raise ValueError(gtype)
            for net in cdata["outputs"].values():
                if vals.get(net, -1) != out:
                    changed = True
                vals[net] = out
    return vals


def build_world(pl, res, iv, ticks=120):
    rec = {}
    def setter(x, y, z, s):
        if s == "minecraft:air":
            rec.pop((x, y, z), None)
        else:
            rec[(x, y, z)] = s
    emit_blocks(setter, pl, res, iv)
    sc = nuc.Schematic.create("t")
    for (x, y, z), s in rec.items():
        sc.set_block_from_string(x, y, z, s)
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    w.tick(ticks)
    return w, rec


def main():
    fname = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(base, "last_placements.json")
    dump = json.load(open(fname))
    placements = dump["placements"]
    col_gap = dump.get("col_gap", 16)

    nls = json.load(open(NETLISTS))
    nl = nls[dump.get("mod", "alu1")]
    pl = place(nl, col_gap=col_gap, row_gap=16)

    r = RB.BuildableRouter(pl, margin=16)
    res = r._materialize(list(placements.keys()), placements, {})
    print(f"materialized: failed={len(res.failed)} {res.failed[:6]} "
          f"wires={res.total_wires()} reps="
          f"{sum(len(v) for v in res.repeaters.values())}", flush=True)

    pb = nl["port_bits"]
    def nm(b):
        return f"n{b}" if not isinstance(b, str) else f"const_{b}"
    a_n, b_n, cin_n = nm(pb["a"][0]), nm(pb["b"][0]), nm(pb["cin"][0])
    op_n = [nm(x) for x in pb["op"]]
    y_n, c_n = nm(pb["y"][0]), nm(pb["cout"][0])
    y_pos = pl.primary_outputs.get(y_n)
    c_pos = pl.primary_outputs.get(c_n)

    driver = {}
    for cname, cdata in nl["cells"].items():
        for net in cdata["outputs"].values():
            driver[net] = cname
    lvl = {}
    def net_lvl(net):
        if net in lvl:
            return lvl[net]
        if net not in driver:
            lvl[net] = 0
            return 0
        c = driver[net]
        m = 0
        for innet in nl["cells"][c]["inputs"].values():
            m = max(m, net_lvl(innet) + 1)
        lvl[net] = m
        return m

    # occupation map of the materialized world (for neighbourhood audits)
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
    # cell-internal voxels (mounts/torches) for the "who is nearby" audit
    cell_occ = {}
    for cname, pc in pl.placed.items():
        for (x, y, z) in pl.occupancy:
            if pc.origin[0] <= x < pc.origin[0] + pc.cell.width and \
               pc.origin[2] <= z < pc.origin[2] + pc.cell.depth and \
               pc.origin[1] <= y < pc.origin[1] + pc.cell.height:
                cell_occ.setdefault((x, y, z), set()).add(cname)

    vecs = []
    for arg in sys.argv[2:]:
        try:
            vecs.append(tuple(int(v) for v in arg.split(",")))
        except ValueError:
            pass
    if not vecs:
        vecs = [(3, 1, 0, 0), (0, 1, 0, 0), (0, 1, 1, 0)]

    for (op, a, bv, cin) in vecs:
        iv = {a_n: a, b_n: bv, cin_n: cin}
        for i in range(4):
            iv[op_n[i]] = (op >> i) & 1
        for inet in nl["inputs"]:
            iv.setdefault(inet, 0)
        exp = logic_sim(nl, iv)
        w, rec = build_world(pl, res, iv)
        def P(x, y, z):
            return w.get_redstone_power(x, y, z)
        print(f"\n{'='*70}\nVECTOR op={op} a={a} b={bv} cin={cin}  "
              f"want y={exp[y_n]} c={exp[c_n]}\n{'='*70}", flush=True)
        yv = 1 if P(*y_pos) > 0 else 0
        cv = 1 if P(*c_pos) > 0 else 0
        print(f"READ y={yv} (pwr={P(*y_pos)})  c={cv} (pwr={P(*c_pos)})",
              flush=True)

        # ---- per-net source power vs expectation ----
        print("\n-- per-net (mismatches only, level-ordered) --", flush=True)
        for net in sorted(pl.net_sources, key=lambda n: (net_lvl(n), n)):
            pos = pl.net_sources[net]
            pwr = P(*pos)
            got = 1 if pwr > 0 else 0
            want = exp.get(net, 0)
            if got != want:
                feeds = [P(k[0] - 1, pl.bounds[0][1], k[2])
                         for k in pl.net_sinks.get(net, [])]
                print(f"  {net:5s} lvl={net_lvl(net):2d} want={want} got={got}"
                      f" src_pwr={pwr} feeds={feeds}", flush=True)

        # ---- per-gate check ----
        print("\n-- gates with wrong feed or output --", flush=True)
        for cname, cdata in nl["cells"].items():
            pc = pl.placed[cname]
            bad_in = []
            for pin, net in cdata["inputs"].items():
                px, py, pz = pc.input_pins[pin]
                fw = P(px - 1, py, pz)
                if (1 if fw > 0 else 0) != exp.get(net, 0):
                    bad_in.append((pin, net, exp.get(net, 0), fw))
            bad_out = []
            for pin, net in cdata["outputs"].items():
                px, py, pz = pc.output_pins[pin]
                pw = P(px, py, pz)
                if (1 if pw > 0 else 0) != exp.get(net, 0):
                    bad_out.append((pin, net, exp.get(net, 0), pw))
            if bad_in or bad_out:
                print(f"  {cname} {cdata['type']} origin={pc.origin}:", flush=True)
                for pin, net, want, fw in bad_in:
                    print(f"    in {pin}={net} want={want} feed_pwr={fw}",
                          flush=True)
                for pin, net, want, pw in bad_out:
                    print(f"    out {pin}={net} want={want} pin_pwr={pw}",
                          flush=True)

        # ---- y/c output path + neighbourhood audit ----
        for tag, pos in (("y", y_pos), ("c", c_pos)):
            print(f"\n-- {tag} output @ {pos} --", flush=True)
            print(f"  source dust pwr={P(*pos)}", flush=True)
            # stub repeater sits one west of pos (pin is two west)
            print(f"  stub rep  pwr={P(pos[0]-1, pos[1], pos[2])}  "
                  f"pin pwr={P(pos[0]-2, pos[1], pos[2])}", flush=True)
            print("  neighbours (foreign conductors in coupling shell):",
                  flush=True)
            for dx, dy, dz in coupling.shell_offsets():
                q = (pos[0] + dx, pos[1] + dy, pos[2] + dz)
                o = occ.get(q)
                cells = cell_occ.get(q)
                if o is not None or cells:
                    print(f"    {q}  net={o} cell={sorted(cells) if cells else '-'}"
                          f"  pwr={P(*q)}", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
