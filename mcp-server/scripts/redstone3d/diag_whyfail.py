"""
diag_whyfail.py — the iterative solver proved that several sinks have 6-18
FEASIBLE tower candidates that the router never finds. That means the failure is
in _bridge_inner's CONTROL FLOW, not in the geometry. This traces exactly which
early `return None` fires for a given sink, so the dead branch can be fixed.

Instrumentation: wrap the helpers _bridge_inner depends on and log their verdicts
in order, then report the first one that aborted the attempt.
"""
import sys, os, json
base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base); sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
from placer import place
from route_buildable import BuildableRouter


def main():
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    want_net = sys.argv[2] if len(sys.argv) > 2 else None
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 4

    pl = place(nls[mod], col_gap=16, row_gap=16)
    r = BuildableRouter(pl, margin=16)

    trace = []
    orig_extend = r._extend_toward
    orig_foot = r._find_foothold
    orig_torch_ok = r._tower_torch_ok
    orig_pick = r._pick_down_tower
    orig_y2 = r._y2_bfs
    orig_inner = r._bridge_inner

    def log(net, goal, what, val):
        if want_net is None or net == want_net:
            trace.append((net, goal, what, val))

    def w_extend(net, placements, goal_xz):
        v = orig_extend(net, placements, goal_xz)
        log(net, goal_xz, "extend_toward",
            "None" if not v else f"anchor={v[0]} dir={v[1]}")
        return v

    def w_foot(net, start):
        v = orig_foot(net, start)
        log(net, start, "find_foothold", "None" if v is None else f"{v[0]}")
        return v

    def w_torch_ok(xz, net):
        v = orig_torch_ok(xz, net)
        log(net, xz, "tower_torch_ok", v)
        return v

    def w_pick(net, pin_xz, cy):
        v = orig_pick(net, pin_xz, cy)
        log(net, pin_xz, f"pick_down_tower(cy={cy})",
            "None" if v is None else f"rot={v[0]}")
        return v

    def w_y2(sources, goal, net, cy):
        v = orig_y2(sources, goal, net, cy)
        log(net, goal, f"y2_bfs(cy={cy},src={len(sources)})",
            "None" if v is None else f"len={len(v)}")
        return v

    def w_inner(net, goal_xz, placements, climbed):
        if want_net is None or net == want_net:
            trace.append((net, goal_xz, ">>> attempt", f"climbed={net in climbed}"))
        v = orig_inner(net, goal_xz, placements, climbed)
        if want_net is None or net == want_net:
            trace.append((net, goal_xz, "<<< result",
                          "None" if v is None else f"{len(v)} placements"))
        return v

    r._extend_toward = w_extend
    r._find_foothold = w_foot
    r._tower_torch_ok = w_torch_ok
    r._pick_down_tower = w_pick
    r._y2_bfs = w_y2
    r._bridge_inner = w_inner

    res = r.route(verbose=False, max_rounds=rounds)
    sh, _ = r._count_shorts(res)
    print(f"[{mod}] shorts={sh} failed={len(res.failed)}: {res.failed}")
    print(f"\ntrace for net={want_net or 'ALL'} ({len(trace)} events, last 60):")
    for (net, goal, what, val) in trace[-60:]:
        print(f"  {net:5s} {str(goal):12s} {what:28s} {val}")


if __name__ == "__main__":
    main()
