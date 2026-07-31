"""diag_sink_room.py — a bridged sink needs a clear DESCENT CORRIDOR: `depth`
consecutive cells running west into its feed cell (gx-1, gz), on some row near
gz. Measure, for every sink, how much room actually exists around the feed cell
(free cells in the west-approach lanes) so we can size a placer-level fix the
way the source-side east-shift fixed source starvation."""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    pl = place(nls[mod], col_gap=16, row_gap=16)
    cell_xz = {(p[0], p[2]) for p in pl.occupancy}
    pins = {}
    for n, p in pl.net_sources.items():
        pins[(p[0], p[2])] = n
    for n, ks in pl.net_sinks.items():
        for p in ks:
            pins[(p[0], p[2])] = n

    def free(c):
        return c not in cell_xz and c not in pins

    print(f"[{mod}] sinks={sum(len(v) for v in pl.net_sinks.values())}")
    tight = []
    for n, ks in sorted(pl.net_sinks.items()):
        for k in ks:
            gx, gz = k[0], k[2]
            # how long a clear west run exists on each candidate row?
            lanes = {}
            for dz in (0, 1, -1, 2, -2):
                zz = gz + dz
                run = 0
                x = gx - 1
                while free((x, zz)) and run < 40:
                    run += 1; x -= 1
                lanes[dz] = run
            best = max(lanes.values())
            if best < 8:
                tight.append((n, (gx, gz), lanes))
            print(f"  {n} sink({gx},{gz}): west-run per dz {lanes}  best={best}")
    print(f"\nsinks with best west-run < 8: {len(tight)}")
    for t in tight:
        print(f"  {t}")


if __name__ == "__main__":
    main()
