import sys, time, faulthandler
sys.path.insert(0, '.'); sys.path.insert(0, '..')
import json
import pathfinder as PF
import route_buildable as RB
from placer import place

log = None
def L(*a, **k):
    print(*a, flush=True, **k)
faulthandler.dump_traceback_later(20, repeat=True, file=open('E:/project/pf/win_faul.log', 'w'))

nls = json.load(open('../riscv_synth/netlists.json'))
pl = place(nls['alu1'], col_gap=16, row_gap=16)
pf = PF.PathFinder(pl, margin=16)
t0 = time.time()
placements, shorts = pf.route(max_rounds=40, verbose=False)
L(f'route: {time.time()-t0:.0f}s shorts={shorts} nets={len(placements)}')
r = RB.BuildableRouter(pl, margin=16)
y0 = pf.y0

# offline children analysis per net
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]
for net in placements:
    pls = placements[net]
    cells = {(p[1], p[3]) for p in pls if p[0] == 'dust' and p[2] == y0}
    src = pl.net_sources.get(net)
    if src is None:
        L(f'  {net}: NO SOURCE'); continue
    start = (src[0], src[2])
    from collections import deque
    depth = {}
    q = deque()
    for dx, dz in _H:
        n0 = (start[0]+dx, start[1]+dz)
        if n0 in cells:
            depth[n0] = 1; q.append((n0, (dx, dz)))
    arrive = {}
    while q:
        cur, came = q.popleft()
        arrive[cur] = came
        for dx, dz in _H:
            nx = (cur[0]+dx, cur[1]+dz)
            if nx in cells and nx not in depth:
                depth[nx] = depth[cur] + 1
                q.append((nx, (dx, dz)))
    children = {}
    for c, came in arrive.items():
        par = (c[0]-came[0], c[1]-came[1])
        children.setdefault(par, []).append(c)
    # cycle check (iterative)
    global_cyc = [False]
    for rc in [c for c in arrive if depth.get(c) == 1]:
        st = [rc]
        path_nodes = set()
        while st:
            c = st.pop()
            if c in path_nodes:
                global_cyc[0] = True
                break
            path_nodes.add(c)
            st.extend(children.get(c, []))
    L(f'  {net}: cells={len(cells)} arrive={len(arrive)} edges={sum(len(v) for v in children.values())} cycle={global_cyc[0]} start={start} start_in_cells={start in cells}')
    if global_cyc[0]:
        L(f'    CYCLIC! cells={sorted(cells)}')

# now run materialize with per-net IR tracing
orig_ir = r._insert_repeaters
def traced(net, pls, res):
    L(f'IR start {net} ({len(pls)} pls)')
    t1 = time.time()
    out = orig_ir(net, pls, res)
    L(f'IR done {net}: {time.time()-t1:.1f}s')
    return out
r._insert_repeaters = traced
L('materialize start')
res = r._materialize(list(placements.keys()), placements, {})
L(f'materialize done: failed={len(res.failed)} wires={res.total_wires()}')
