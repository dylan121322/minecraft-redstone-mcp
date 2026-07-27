"""Test the global-grid channel router on alu1 and measure results."""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "redstone3d"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "riscv_synth"))

from placer import place
from yosys_frontend import compile_verilog
from route_channel import ChannelRouter
from verify_channel_mchprs import legality, emit, netname
from collections import Counter
import nucleation as nuc

VERILOG = os.path.join(os.path.dirname(__file__), "..", "riscv_synth", "alu1.v")

def run():
    nl = compile_verilog(VERILOG, top="alu1")
    print(f"alu1: {len(nl['cells'])} gates",
          dict(Counter(c['type'] for c in nl['cells'].values())))

    pl = place(nl, col_gap=16, row_gap=10)
    print(f"Placement: {pl.bounds}")

    r = ChannelRouter(pl)
    t0 = time.time()
    res = r.route(verbose=False)
    t1 = time.time()
    sh, fl = legality(res, pl)
    print(f"Route: {res.total_wires()} wires, {len(res.supports)} supports, "
          f"{sum(len(v) for v in res.repeaters.values())} reps")
    print(f"  shorts={sh}  floats={fl}  failed={res.failed}")
    print(f"  route_time={t1-t0:.2f}s")

    # Output nets check
    output_nets = [n for n in pl.primary_outputs if n not in res.wires or len(res.wires.get(n, set())) == 0]
    if output_nets:
        print(f"  WARNING: output nets un-routed: {output_nets}")

    # Check failed nets
    if res.failed:
        print(f"  FAILED NETS: {res.failed}")

    # Detailed shorts
    if sh > 0:
        owner = dict(res.wire_owner)
        SHELL = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]
        shorts_by_layer = Counter()
        shorts_by_net = Counter()
        seen = set()
        for p, net in owner.items():
            x, y, z = p
            for dx, dz in SHELL:
                o = owner.get((x+dx, y, z+dz))
                if o is not None and o != net:
                    pair = (min(net,o), max(net,o), y)
                    if pair not in seen:
                        seen.add(pair)
                        shorts_by_layer[y] += 1
                        shorts_by_net[pair[0]] += 1
                        shorts_by_net[pair[1]] += 1
            for dy in (1, -1):
                o = owner.get((x, y+dy, z))
                if o is not None and o != net:
                    pair = (min(net,o), max(net,o), y)
                    if pair not in seen:
                        seen.add(pair)
                        shorts_by_layer[y if dy == 1 else y] += 1
                        shorts_by_net[pair[0]] += 1
                        shorts_by_net[pair[1]] += 1
        print(f"  Shorts by layer: {dict(shorts_by_layer)}")
        print(f"  Shorts by net (top 10): {shorts_by_net.most_common(10)}")

    # Quick MCHPRS test (single vector if shorts == 0 and all nets routed)
    if sh == 0 and not output_nets and not res.failed:
        print("\nRunning single-vector MCHPRS test...")
        pb = nl["port_bits"]
        y_n = netname(pb["y"][0])
        cout_n = netname(pb["cout"][0])
        probes = dict(pl.primary_outputs)

        from mchprs_sim import simulate_vectors

        def build(schem, inputs):
            emit(schem, pl, res, inputs)

        tvs = [{"inputs": {}, "expected": {y_n: 0, cout_n: 0}}]
        t2 = time.time()
        results = simulate_vectors(build, list(nl["inputs"]), probes, tvs,
                                    ticks=30, lamp_outputs=False)
        t3 = time.time()
        for r in results:
            mark = "OK" if r["match"] else "X"
            print(f"  [{mark}] inputs=0: got y={r['actual'].get(y_n)} cout={r['actual'].get(cout_n)}")
        print(f"  sim_time={t3-t2:.1f}s")
    else:
        print("\nSkipping MCHPRS (shorts or errors present)")

    return sh, fl


if __name__ == "__main__":
    sh, fl = run()
    sys.exit(0 if sh == 0 and fl == 0 else 1)
