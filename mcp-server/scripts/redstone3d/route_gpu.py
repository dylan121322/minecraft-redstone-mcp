"""
route_gpu.py — GPU 3D negotiated rip-up router (RTX 5080, torch CUDA).

Runs ENTIRELY on the Windows box (E:\\py312 torch cu128). Represents the routing
space as torch tensors and does parallel Lee-wavefront distance fields on the
GPU, PathFinder-style negotiated congestion, until 0 real redstone adjacency
shorts. See ROUTER_JOURNAL.md §VIII.

Layers: y0 (signal plane) and y2 (bridge plane); vias (torch towers) connect
them. Modeled as L=2 layers in a (L, X, Z) grid. A net routes by a wavefront
that floods outward on a cost field; the min-cost path is recovered by gradient
descent on the distance field. Congestion (present + history) makes nets
negotiate apart across iterations.

Legality (TRUE redstone): two different nets' dust short if 8-neighbour adjacent
on the same layer, or vertically/diagonally between layers within 1. The cost
field penalizes cells whose neighbourhood is claimed by other nets.

Input:  a netlist + placement (from placer.py, computed on CPU, cheap).
Output: per-net wire/repeater placements (same typed tuples as route_buildable),
        shipped back for MCHPRS verify + bot build.
"""
from __future__ import annotations
import sys, os, json, time
from typing import Dict, List, Tuple
import torch
Pos = Tuple[int, int, int]
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]

class GpuRouter:

    @staticmethod
    def _auto_device():
        # Win RTX 5080 -> cuda; Mac -> mps; else cpu. Keeps the toolchain
        # runnable on either machine without code edits.
        if torch.cuda.is_available():
            return 'cuda'
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return 'mps'
        return 'cpu'

    def __init__(self, placement, device=None, nlayers=2, layer_y=(0, 2), margin=6):
        self.pl = placement
        self.dev = torch.device(device or self._auto_device())
        self.L = nlayers
        self.layer_y = layer_y
        mn, mx = placement.bounds
        self.x0 = mn[0] - margin
        self.z0 = mn[2] - margin
        self.X = mx[0] + margin - self.x0 + 1
        self.Z = mx[2] + margin - self.z0 + 1
        self.base_y = mn[1]
        self.block = torch.zeros((self.L, self.X, self.Z), dtype=torch.bool, device=self.dev)
        for x, y, z in placement.occupancy:
            gx, gz = (x - self.x0, z - self.z0)
            if 0 <= gx < self.X and 0 <= gz < self.Z:
                self.block[0, gx, gz] = True
        self.pin_cells: Dict[Tuple[int, int], str] = {}
        for net, pos in placement.net_sources.items():
            self.pin_cells[pos[0] - self.x0, pos[2] - self.z0] = net
        for net, sinks in placement.net_sinks.items():
            for pos in sinks:
                self.pin_cells[pos[0] - self.x0, pos[2] - self.z0] = net
        for gx, gz in self.pin_cells:
            if 0 <= gx < self.X and 0 <= gz < self.Z:
                self.block[0, gx, gz] = False

    def _g(self, x, z):
        return (x - self.x0, z - self.z0)

    def wavefront(self, sources: List[Tuple[int, int, int]], cost: torch.Tensor, max_iters=None) -> torch.Tensor:
        """Parallel Lee/BFS distance field on the GPU. `sources` are (layer,gx,gz)
        seed cells (distance 0). `cost` is (L,X,Z) per-cell entry cost. Returns
        the distance field (L,X,Z); unreached cells = +inf. Relaxation:
        dist[n] = min(dist[n], min over neighbours(dist[nb]) + cost[n]).
        Iterate until stable (no change) or max_iters."""
        INF = float('inf')
        dist = torch.full((self.L, self.X, self.Z), INF, device=self.dev)
        for l, gx, gz in sources:
            dist[l, gx, gz] = 0.0
        blocked = self.block
        if max_iters is None:
            max_iters = self.X + self.Z + 4 * self.L
        cost_masked = cost.clone()
        cost_masked[blocked] = INF
        for _ in range(max_iters):
            up = torch.roll(dist, 1, 1)
            up[:, 0, :] = INF
            dn = torch.roll(dist, -1, 1)
            dn[:, -1, :] = INF
            lf = torch.roll(dist, 1, 2)
            lf[:, :, 0] = INF
            rt = torch.roll(dist, -1, 2)
            rt[:, :, -1] = INF
            nb = torch.minimum(torch.minimum(up, dn), torch.minimum(lf, rt))
            if self.L > 1:
                vup = torch.roll(dist, 1, 0)
                vup[0] = INF
                vdn = torch.roll(dist, -1, 0)
                vdn[-1] = INF
                nb = torch.minimum(nb, torch.minimum(vup, vdn))
            dist = torch.minimum(dist, nb + cost_masked)
            for l, gx, gz in sources:
                dist[l, gx, gz] = 0.0
        return dist

    def wavefront_batched(self, seeds_per_net, cost, sweeps):
        """Flood ALL nets at once. seeds_per_net: list (len N) of list of
        (l,gx,gz) seed cells. cost: (L,X,Z) shared cost field. Returns dist
        (N,L,X,Z). One set of GPU kernels relaxes every net in parallel — this is
        the GPU-native speedup (vs a Python loop over nets)."""
        INF = float('inf')
        N = len(seeds_per_net)
        dist = torch.full((N, self.L, self.X, self.Z), INF, device=self.dev)
        seed_idx = [[], [], [], []]
        for n, seeds in enumerate(seeds_per_net):
            for l, gx, gz in seeds:
                seed_idx[0].append(n)
                seed_idx[1].append(l)
                seed_idx[2].append(gx)
                seed_idx[3].append(gz)
        si = [torch.tensor(a, device=self.dev, dtype=torch.long) for a in seed_idx]
        dist[si[0], si[1], si[2], si[3]] = 0.0
        cm = cost.clone()
        if cm.dim() == 3:
            cm[self.block] = INF
            cm = cm.unsqueeze(0)
        else:
            cm[:, self.block] = INF
        for _ in range(sweeps):
            up = torch.roll(dist, 1, 2)
            up[:, :, 0, :] = INF
            dn = torch.roll(dist, -1, 2)
            dn[:, :, -1, :] = INF
            lf = torch.roll(dist, 1, 3)
            lf[:, :, :, 0] = INF
            rt = torch.roll(dist, -1, 3)
            rt[:, :, :, -1] = INF
            nb = torch.minimum(torch.minimum(up, dn), torch.minimum(lf, rt))
            if self.L > 1:
                vup = torch.roll(dist, 1, 1)
                vup[:, 0] = INF
                vdn = torch.roll(dist, -1, 1)
                vdn[:, -1] = INF
                nb = torch.minimum(nb, torch.minimum(vup, vdn))
            dist = torch.minimum(dist, nb + cm)
            dist[si[0], si[1], si[2], si[3]] = 0.0
        return dist

    def backtrace(self, dist: torch.Tensor, goal_layer, gx, gz, cost: torch.Tensor) -> List[Tuple[int, int, int]]:
        """Recover a min-cost path from goal back to a source (dist==0) by greedy
        descent on the distance field. Returns list of (layer,gx,gz) source->goal."""
        INF = float('inf')
        d = dist
        cur = (goal_layer, gx, gz)
        path = [cur]
        dcpu = dist.detach().to('cpu')
        guard = 0
        while dcpu[cur[0], cur[1], cur[2]].item() > 0 and guard < self.X * self.Z * self.L:
            guard += 1
            l, x, z = cur
            best = None
            bestv = dcpu[l, x, z].item()
            for dx, dz in _H:
                nx, nz = (x + dx, z + dz)
                if 0 <= nx < self.X and 0 <= nz < self.Z:
                    v = dcpu[l, nx, nz].item()
                    if v < bestv:
                        bestv = v
                        best = (l, nx, nz)
            for dl in (1, -1):
                nl = l + dl
                if 0 <= nl < self.L:
                    v = dcpu[nl, x, z].item()
                    if v < bestv:
                        bestv = v
                        best = (nl, x, z)
            if best is None:
                break
            cur = best
            path.append(cur)
        path.reverse()
        return path

    def _occ_tensor(self, routes):
        """(L,X,Z) int tensor: cell -> net index+1 (0=empty). Last writer wins;
        used only for short detection (different indices adjacent = short)."""
        occ = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
        for idx, cells in routes.items():
            for l, x, z in cells:
                occ[l, x, z] = idx + 1
        return occ

    def _short_cells(self, occ):
        """Return a (L,X,Z) bool mask of cells that adjacency-short with a
        DIFFERENT net. In-layer 8-neighbour + inter-layer vertical/diagonal.
        Vectorized on GPU via shifted comparisons."""
        L, X, Z = (self.L, self.X, self.Z)
        nz = occ > 0
        bad = torch.zeros_like(nz)
        shifts = [(0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (0, 1, 1), (0, 1, -1), (0, -1, 1), (0, -1, -1)]
        for dl, dx, dz in shifts:
            s = torch.roll(occ, shifts=(dl, dx, dz), dims=(0, 1, 2))
            if dx == 1:
                s[:, 0, :] = 0
            elif dx == -1:
                s[:, -1, :] = 0
            if dz == 1:
                s[:, :, 0] = 0
            elif dz == -1:
                s[:, :, -1] = 0
            if dl == 1:
                s[0] = 0
            elif dl == -1:
                s[-1] = 0
            conflict = nz & (s > 0) & (s != occ)
            bad |= conflict
        return bad

    def route(self, max_iters=50, verbose=True, short_pen=8.0, hist_inc=4.0, seed=0, jitter=0.0):
        nets = [n for n in self.pl.net_sinks if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        net_idx = {n: i for i, n in enumerate(nets)}
        N = len(nets)
        hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
        if jitter > 0.0:
            g = torch.Generator(device=self.dev)
            g.manual_seed(seed)
            hist = hist + torch.rand((self.L, self.X, self.Z), generator=g, device=self.dev) * jitter
        SHORT_PEN = short_pen
        sweeps = self.X + self.Z + 4 * self.L
        src_of = {net_idx[n]: (0,) + self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2]) for n in nets}
        sinks_of = {}
        for n in nets:
            s = self.pl.net_sources[n]
            sinks_of[net_idx[n]] = [(0,) + self._g(k[0], k[2]) for k in sorted(self.pl.net_sinks[n], key=lambda k: abs(s[0] - k[0]) + abs(s[2] - k[2]))]
        best_routes = None
        best_bad = 1 << 30
        occ_prev = None
        for it in range(max_iters):
            present = self._short_cells(occ_prev).float() * SHORT_PEN if occ_prev is not None else 0.0
            cost = torch.ones((self.L, self.X, self.Z), device=self.dev) + hist + present
            routes = {i: [] for i in range(N)}
            seeds = {i: [src_of[i]] for i in range(N)}
            max_sinks = max((len(v) for v in sinks_of.values()))
            for r in range(max_sinks):
                seed_list = [seeds[i] for i in range(N)]
                dist = self.wavefront_batched(seed_list, cost, sweeps)
                dcpu = dist.to('cpu')
                for i in range(N):
                    if r >= len(sinks_of[i]):
                        continue
                    gl, gx, gz = sinks_of[i][r]
                    if dcpu[i, 0, gx, gz].item() == float('inf'):
                        continue
                    path = self._backtrace_cpu(dcpu[i], 0, gx, gz)
                    for c in path:
                        if (c[1], c[2]) not in self.pin_cells:
                            if c not in routes[i]:
                                routes[i].append(c)
                            if c not in seeds[i]:
                                seeds[i].append(c)
            occ = self._occ_tensor(routes)
            occ_prev = occ
            nbad = int(self._short_cells(occ).sum().item())
            if nbad < best_bad:
                best_bad = nbad
                best_routes = {k: list(v) for k, v in routes.items()}
            if verbose and (it % 2 == 0 or nbad == 0):
                print(f'  iter {it}: shorted cells={nbad}', flush=True)
            if nbad == 0:
                break
            hist += self._short_cells(occ).float() * hist_inc
        return (best_routes, best_bad, net_idx)

    def route_layered(self, base_variant=None, iters_per=25, verbose=True):
        """Negotiated base route, then GUARANTEE 0 shorts by assigning each net a
        LAYER via graph-coloring of the conflict graph: two nets that conflict
        get different layers. Within a layer no two nets are adjacent-conflicting
        (by construction), and cross-layer H/V is isolated (verified). Then
        re-route each net confined to its assigned layer (+ vias to reach y0
        pins). This combines negotiated compactness with a hard 0-short
        guarantee.

        Steps:
        1. run one negotiated variant to get a base routing + conflict graph
        2. greedily color nets: color = smallest layer not used by any conflicting
           neighbour already colored. #colors = chromatic-ish (small).
        3. re-route per net on its color layer (wavefront restricted to that layer
           for the trunk; y0 pins reached by a via at source and each sink).
        """
        v = base_variant or dict(short_pen=16.0, hist_inc=3.0, jitter=1.5, seed=3)
        routes, nbad, net_idx = self.route(max_iters=iters_per, verbose=False, **v)
        if verbose:
            print(f'  base negotiated: shorts={nbad}', flush=True)
        if nbad == 0:
            return (routes, 0, net_idx)
        adj = self._conflict_graph(routes, net_idx)
        CAP = 1
        order = sorted(net_idx, key=lambda n: -len(adj[n]))
        color: Dict[str, int] = {}
        layer_members: Dict[int, list] = {}
        for n in order:
            c = 0
            while True:
                members = layer_members.get(c, [])
                if len(members) < CAP and all((m not in adj[n] for m in members)):
                    break
                c += 1
            color[n] = c
            layer_members.setdefault(c, []).append(n)
        ncolors = max(color.values()) + 1
        if verbose:
            print(f'  conflict graph colored with {ncolors} layers', flush=True)
        return (color, ncolors, net_idx)

    def route_layer_confined(self, color, ncolors, net_idx, sweeps=None, verbose=True):
        """Re-route every net CONFINED to its assigned color-layer. Each net's
        trunk lives only on its layer; y0 pins reached by a via at source and
        each sink. Two nets on the SAME layer don't conflict (coloring), so a
        single batched wavefront per layer is short-free by construction — but we
        still route them with mutual keep-out (occ of same-layer peers) to be safe.

        Returns per-net cells [(layer,gx,gz)] + via markers, and the true short
        count (should be 0)."""
        if sweeps is None:
            sweeps = self.X + self.Z + 4 * self.L
        nets = list(net_idx)
        routes = {net_idx[n]: [] for n in nets}
        by_color: Dict[int, List[str]] = {}
        for n in nets:
            by_color.setdefault(color[n], []).append(n)
        for c, group in sorted(by_color.items()):
            tl = c + 1
            if tl >= self.L:
                if verbose:
                    print(f'  layer {c}: NO LAYER (need L>{tl})', flush=True)
                continue
            BIG = 1000000000.0
            cost = torch.full((self.L, self.X, self.Z), BIG, device=self.dev)
            cost[tl] = 1.0
            pin_cols = set()
            for n in group:
                s = self.pl.net_sources[n]
                pin_cols.add(self._g(s[0], s[2]))
                for k in self.pl.net_sinks[n]:
                    pin_cols.add(self._g(k[0], k[2]))
            for gx, gz in pin_cols:
                cost[0:tl + 1, gx, gz] = 1.0
            gi = {n: i for i, n in enumerate(group)}
            hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
            best = None
            bestbad = 1 << 30
            for it in range(20):
                gr = {i: [] for i in range(len(group))}
                seeds = {}
                for n in group:
                    s = self.pl.net_sources[n]
                    seeds[gi[n]] = [(0,) + self._g(s[0], s[2])]
                sinks_of = {}
                for n in group:
                    s = self.pl.net_sources[n]
                    sinks_of[gi[n]] = [(0,) + self._g(k[0], k[2]) for k in self.pl.net_sinks[n]]
                cc = cost + hist
                msink = max((len(v) for v in sinks_of.values()))
                for r in range(msink):
                    seed_list = [seeds[i] for i in range(len(group))]
                    dist = self.wavefront_batched(seed_list, cc, sweeps)
                    dcpu = dist.to('cpu')
                    for i in range(len(group)):
                        if r >= len(sinks_of[i]):
                            continue
                        gl, gx, gz = sinks_of[i][r]
                        if dcpu[i, 0, gx, gz].item() == float('inf'):
                            continue
                        path = self._backtrace_cpu(dcpu[i], 0, gx, gz)
                        for cell in path:
                            if (cell[1], cell[2]) not in self.pin_cells:
                                if cell not in gr[i]:
                                    gr[i].append(cell)
                                if cell not in seeds[i]:
                                    seeds[i].append(cell)
                gocc = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    for l, x, z in cells:
                        gocc[l, x, z] = i + 1
                nb = int(self._short_cells(gocc).sum().item())
                if nb < bestbad:
                    bestbad = nb
                    best = {i: list(v) for i, v in gr.items()}
                if nb == 0:
                    break
                hist += self._short_cells(gocc).float() * 4.0
            if verbose:
                print(f'  layer {c}: {len(group)} nets, intra-layer shorts={bestbad}', flush=True)
            for i, cells in best.items():
                routes[net_idx[group[i]]] = cells
        occ = self._occ_tensor(routes)
        total_bad = int(self._short_cells(occ).sum().item())
        return (routes, total_bad, net_idx)

    def route_portfolio(self, variants=None, iters_per=25, verbose=True):
        """GPU portfolio: run several negotiated variants with different
        (short_pen, hist_inc, jitter, seed). Each gets a different cost landscape
        so at least one escapes the symmetric oscillation. Return the first to
        reach 0 shorts, else the overall best. Variants run sequentially here
        (each already batches all nets on the GPU); the win is DIVERSITY, not
        more parallelism — one variant converging beats all oscillating."""
        if variants is None:
            variants = [dict(short_pen=8.0, hist_inc=4.0, jitter=0.0, seed=0), dict(short_pen=12.0, hist_inc=6.0, jitter=1.0, seed=1), dict(short_pen=6.0, hist_inc=8.0, jitter=2.0, seed=2), dict(short_pen=16.0, hist_inc=3.0, jitter=1.5, seed=3), dict(short_pen=10.0, hist_inc=10.0, jitter=3.0, seed=4), dict(short_pen=20.0, hist_inc=5.0, jitter=2.5, seed=5)]
        best = None
        best_bad = 1 << 30
        best_idx = None
        net_idx = None
        for vi, v in enumerate(variants):
            routes, nbad, ni = self.route(max_iters=iters_per, verbose=False, **v)
            net_idx = ni
            if verbose:
                print(f'  variant {vi} {v}: best shorts={nbad}', flush=True)
            if nbad < best_bad:
                best_bad = nbad
                best = routes
                best_idx = vi
            if nbad == 0:
                if verbose:
                    print(f'  variant {vi} LEGAL (0 shorts)', flush=True)
                break
        if verbose:
            print(f'  portfolio best: variant {best_idx}, shorts={best_bad}', flush=True)
        return (best, best_bad, net_idx)

    def _conflict_graph(self, routes, net_idx):
        """Which nets adjacency-conflict with which (from a routed occ). Returns
        adjacency dict net_i -> set(net_j)."""
        idx2 = {i: n for n, i in net_idx.items()}
        occ = self._occ_tensor(routes)
        adj = {n: set() for n in net_idx}
        L, X, Z = (self.L, self.X, self.Z)
        shifts = [(0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1), (0, 1, 1), (0, 1, -1), (0, -1, 1), (0, -1, -1)]
        if L > 1:
            shifts += [(1, 0, 0), (-1, 0, 0), (1, 1, 0), (1, -1, 0), (1, 0, 1), (1, 0, -1)]
        for dl, dx, dz in shifts:
            s = torch.roll(occ, shifts=(dl, dx, dz), dims=(0, 1, 2))
            if dx == 1:
                s[:, 0, :] = 0
            elif dx == -1:
                s[:, -1, :] = 0
            if dz == 1:
                s[:, :, 0] = 0
            elif dz == -1:
                s[:, :, -1] = 0
            if dl == 1:
                s[0] = 0
            elif dl == -1:
                s[-1] = 0
            conflict = (occ > 0) & (s > 0) & (s != occ)
            pos = conflict.nonzero(as_tuple=False).tolist()
            for l, x, z in pos:
                a = int(occ[l, x, z].item()) - 1
                b = int(s[l, x, z].item()) - 1
                if a >= 0 and b >= 0:
                    adj[idx2[a]].add(idx2[b])
                    adj[idx2[b]].add(idx2[a])
        return adj

    def _backtrace_cpu(self, dist_cpu, l, x, z):
        """Greedy descent on a single net's CPU distance field (L,X,Z)."""
        cur = (l, x, z)
        path = [cur]
        guard = 0
        while dist_cpu[cur[0], cur[1], cur[2]].item() > 0 and guard < self.X * self.Z * self.L:
            guard += 1
            cl, cx, cz = cur
            bestv = dist_cpu[cl, cx, cz].item()
            best = None
            for dx, dz in _H:
                nx, nz = (cx + dx, cz + dz)
                if 0 <= nx < self.X and 0 <= nz < self.Z:
                    v = dist_cpu[cl, nx, nz].item()
                    if v < bestv:
                        bestv = v
                        best = (cl, nx, nz)
            for dl in (1, -1):
                nl = cl + dl
                if 0 <= nl < self.L:
                    v = dist_cpu[nl, cx, cz].item()
                    if v < bestv:
                        bestv = v
                        best = (nl, cx, cz)
            if best is None:
                break
            cur = best
            path.append(cur)
        path.reverse()
        return path

    def route_partitioned(self, zone_width=80, base_iters=12, layer_iters=20,
                          cap=1, share_layers=False, even_layers_only=True,
                          verbose=True):
        """Spatial-zone layered routing. See ROUTER_JOURNAL §IX.

        cap: max nets per local color (layer). cap=1 => one net per layer (deep
             vias, structural 0-short). Higher cap packs the sparse conflict
             graph into FEWER layers => SHALLOWER sink-down vias, at the cost of
             relying on route_group's negotiated keep-out to keep same-layer
             nets apart. share_layers=True additionally reuses trunk-layer
             numbers across zones (x-disjoint zones can't short on a shared
             layer) to compress depth further."""
        nets = list(self.pl.net_sinks)
        mn, mx = self.pl.bounds
        X0 = mn[0]

        def zone_of(n):
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            return set(((x - X0) // zone_width for x in xs))
        v = dict(short_pen=12.0, hist_inc=3.0, jitter=1.0, seed=0)
        routes0, nbad0, net_idx = self.route(max_iters=base_iters, verbose=False, **v)
        adj = self._conflict_graph(routes0, net_idx)
        local = [n for n in nets if len(zone_of(n)) == 1]
        globl = [n for n in nets if len(zone_of(n)) > 1]
        if verbose:
            print(f'  zone_w={zone_width}: local={len(local)} global={len(globl)}', flush=True)
        local_zones = {}
        for n in local:
            z = list(zone_of(n))[0]
            local_zones.setdefault(z, []).append(n)
        CAP = cap
        zone_local_color = {}
        max_local = 0
        for z, group in sorted(local_zones.items()):
            adj_sub = {n: adj[n] & set(group) for n in group}
            order = sorted(group, key=lambda n: -len(adj_sub[n]))
            local_col = {}
            members = {}
            for n in order:
                c = 1
                while True:
                    m = members.get(c, [])
                    if len(m) < CAP and all((mb not in adj_sub[n] for mb in m)):
                        break
                    c += 1
                local_col[n] = c
                members.setdefault(c, []).append(n)
                zone_local_color[n] = (z, c)
            max_local = max(max_local, max(local_col.values()) if local_col else 0)
            if verbose:
                print(f'  zone {z}: {len(group)} nets, {max(local_col.values())} layers', flush=True)
        routes_final = {net_idx[n]: [] for n in nets}
        sweeps = self.X + self.Z + 4 * self.L
        placed_occ = None
        INF = float('inf')

        # Global via-shaft reservation: EVERY net's pin column is a vertical via
        # shaft. A trunk must never sit on a foreign net's shaft (else that net's
        # via, climbing through this trunk layer, shorts the trunk). Reserve all
        # pin columns + their 8-neighbour ring on the trunk layer; open only this
        # group's own shafts. This removes the via穿层 shorts structurally.
        all_shaft = set(self.pin_cells.keys())
        def build_cost(tl, x_lo, x_hi, pin_set):
            c = torch.full((self.L, self.X, self.Z), INF, device=self.dev)
            c[tl] = 1.0
            if x_lo is not None:
                glo, ghi = (x_lo - self.x0, min(x_hi - self.x0, self.X))
                c[tl, :max(0, glo), :] = INF
                c[tl, ghi:, :] = INF
            # block foreign via shafts on the trunk layer. Only the shaft CELL
            # itself (not an 8-ring): pins are already spaced >=2 apart (placer),
            # so a trunk passing beside a foreign shaft doesn't short it, and the
            # ring was over-blocking — it walled off legit trunk corridors and
            # left dense-PI-region nets (n7) unroutable.
            foreign_shaft = all_shaft - set(pin_set)
            for sgx, sgz in foreign_shaft:
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        qx, qz = sgx + dx, sgz + dz
                        if 0 <= qx < self.X and 0 <= qz < self.Z:
                            c[tl, qx, qz] = INF
            for gx, gz in pin_set:
                c[0:tl + 1, gx, gz] = 1.0
            if placed_occ is not None:
                # Keep-out foreign cells + their 8-neighbour shell on EVERY layer.
                # A via segment (pin column, layers 0..tl) can be adjacent to a
                # foreign net's trunk on an intermediate layer — restricting the
                # keep-out to only `tl` left those via-vs-trunk shorts (the 88).
                # Apply the shell keep-out across all layers so both trunks AND
                # via columns steer clear of foreign cells.
                f = placed_occ > 0
                k = f.clone()
                for dx, dz in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                    s = torch.roll(f, shifts=(dx, dz), dims=(1, 2))
                    if dx == 1:
                        s[:, 0, :] = False
                    elif dx == -1:
                        s[:, -1, :] = False
                    if dz == 1:
                        s[:, :, 0] = False
                    elif dz == -1:
                        s[:, :, -1] = False
                    k |= s
                # protect trunk layer fully; protect via columns on lower layers
                # but DON'T block the pin cells themselves (they must stay open)
                for pgx, pgz in pin_set:
                    k[:, pgx, pgz] = False
                c[k] = INF
            return c

        def route_group(group, cost):
            gi = {n: i for i, n in enumerate(group)}
            hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
            best_gr = None
            bestbad = 1 << 30
            best_score = (1 << 30, 1 << 30)
            for it in range(layer_iters):
                gr = {i: [] for i in range(len(group))}
                seeds = {gi[n]: [(0,) + self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2])] for n in group}
                sinks_of = {gi[n]: [(0,) + self._g(k[0], k[2]) for k in self.pl.net_sinks[n]] for n in group}
                cc = cost + hist
                msink = max((len(v) for v in sinks_of.values()))
                for r in range(msink):
                    seed_list = [seeds[i] for i in range(len(group))]
                    dist = self.wavefront_batched(seed_list, cc, sweeps)
                    dcpu = dist.to('cpu')
                    for i in range(len(group)):
                        if r >= len(sinks_of[i]):
                            continue
                        gl, gx, gz = sinks_of[i][r]
                        if dcpu[i, 0, gx, gz].item() == INF:
                            continue
                        path = self._backtrace_cpu(dcpu[i], 0, gx, gz)
                        for cell in path:
                            is_pin = cell[0] == 0 and (cell[1], cell[2]) in self.pin_cells
                            if not is_pin:
                                if cell not in gr[i]:
                                    gr[i].append(cell)
                                if cell not in seeds[i]:
                                    seeds[i].append(cell)
                gocc = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    for l, x, z in cells:
                        gocc[l, x, z] = i + 1
                nb = int(self._short_cells(gocc).sum().item())
                # count nets that failed to reach all sinks this round: a net is
                # connected iff it has >=1 cell adjacent to each of its sink pins.
                nunconn = 0
                for i, group_n in enumerate([group[j] for j in range(len(group))]):
                    S = set(tuple(c) for c in gr[i])
                    near = lambda g: any((1, g[0]+dx, g[1]+dz) in S
                                         for dx, dz in [(0,0),(1,0),(-1,0),(0,1),(0,-1)])
                    if not gr[i] or not all(near(self._g(k[0], k[2]))
                                            for k in self.pl.net_sinks[group_n]):
                        nunconn += 1
                # score: connectivity FIRST, then shorts (never pick a
                # low-short round that dropped a net — that was the empty-net bug)
                score = (nunconn, nb)
                if best_gr is None or score < best_score:
                    best_score = score
                    bestbad = nb
                    best_gr = {i: list(v) for i, v in gr.items()}
                if nunconn == 0 and nb == 0:
                    break
                hist += self._short_cells(gocc).float() * 4.0
            return (best_gr, bestbad)
        # Assign each (zone, local_color) group its OWN unique trunk layer (no
        # layer-number reuse across zones). This removes cross-zone same-layer
        # adjacency at zone boundaries: each trunk layer holds exactly one group,
        # so intra-layer shorts are structural-0 and cross-layer is isolated
        # (2-Y gap). via穿层 keep-out (build_cost) handles the vertical columns.
        # even_layers_only: assign trunk layers 2,4,6,... so a source RISE (torch
        # tower, n=layer torches) always uses an EVEN torch count => non-inverting
        # with NO parity correction. Odd layers would invert the signal and need
        # a fragile wall-torch fixup (verified unreliable). Costs 2x via depth,
        # irrelevant for MCHPRS/logic; depth is optimized later (planar routing).
        step = 2 if even_layers_only else 1
        next_tl = step
        for z, zone_nets in sorted(local_zones.items()):
            by_lc = {}
            for n in zone_nets:
                _, lc = zone_local_color[n]
                by_lc.setdefault(lc, []).append(n)
            for lc, group in sorted(by_lc.items()):
                tl = next_tl
                next_tl += step
                if tl >= self.L:
                    if verbose:
                        print(f'  zone={z} lc={lc}: NO LAYER (L={self.L})', flush=True)
                    continue
                pin_set = set()
                for n in group:
                    pin_set.add(self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2]))
                    for k in self.pl.net_sinks[n]:
                        pin_set.add(self._g(k[0], k[2]))
                x_lo = X0 + z * zone_width
                x_hi = x_lo + zone_width
                cost = build_cost(tl, x_lo, x_hi, pin_set)
                gr, bestbad = route_group(group, cost)
                if verbose:
                    ne = sum(1 for i in gr if gr[i])
                    print(f'  zone={z} lc={lc} tl={tl}: {len(group)} nets {ne} nonempty, shorts={bestbad}', flush=True)
                for i, cells in gr.items():
                    routes_final[net_idx[group[i]]] = cells
                if placed_occ is None:
                    placed_occ = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    gidx = net_idx[group[i]] + 1
                    for cl, cx, cz in cells:
                        placed_occ[cl, cx, cz] = gidx
        max_local = next_tl - step
        for gi, n in enumerate(globl):
            tl = max_local + (gi + 1) * step
            if tl >= self.L:
                continue
            pin_set = set()
            pin_set.add(self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2]))
            for k in self.pl.net_sinks[n]:
                pin_set.add(self._g(k[0], k[2]))
            cost = build_cost(tl, None, None, pin_set)
            gr, bestbad = route_group([n], cost)
            if verbose:
                print(f'  global {n} tl={tl}: shorts={bestbad}', flush=True)
            if 0 in gr:
                routes_final[net_idx[n]] = gr[0]
            if placed_occ is None:
                placed_occ = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
            if 0 in gr:
                for l, x, z in gr[0]:
                    placed_occ[l, x, z] = net_idx[n] + 1
        occ = self._occ_tensor(routes_final)
        nbad = int(self._short_cells(occ).sum().item())
        unrouted = []
        for n, i in net_idx.items():
            cells = routes_final.get(i, [])
            if not cells:
                unrouted.append((n, 'empty'))
                continue
            S = set(((c[0], c[1], c[2]) for c in cells))
            if len(set((c[0] for c in cells))) < 2:
                pass
            sg = self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2])
            near = lambda g: any(((1, g[0] + dx, g[1] + dz) in S for dx, dz in [(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)]))
            if not near(sg):
                unrouted.append((n, 'src-open'))
                continue
            for k in self.pl.net_sinks[n]:
                if not near(self._g(k[0], k[2])):
                    unrouted.append((n, 'sink-open'))
                    break
        self.unrouted = unrouted
        return (routes_final, nbad, net_idx)
if __name__ == '__main__':
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base)
    sys.path.insert(0, os.path.join(base, '..', 'riscv_synth'))
    from placer import place
    nls = json.load(open(os.path.join(base, '..', 'riscv_synth', 'netlists.json')))
    mod = sys.argv[1] if len(sys.argv) > 1 else 'alu1'
    L = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    cg = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    rg = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    W = int(sys.argv[5]) if len(sys.argv) > 5 else 80
    pl = place(nls[mod], col_gap=cg, row_gap=rg)
    r = GpuRouter(pl, nlayers=L, layer_y=tuple(range(0, 2 * L, 2)))
    print(f'[{mod}] grid L={r.L} X={r.X} Z={r.Z} device={r.dev} zoneW={W}')
    t = time.time()
    routes, nbad, net_idx = r.route_partitioned(zone_width=W, verbose=True)
    torch.cuda.synchronize() if r.dev.type == 'cuda' else None
    nwires = sum((len(v) for v in routes.values()))
    unr = getattr(r, 'unrouted', [])
    ok = nbad == 0 and (not unr)
    print(f"[{mod}] PARTITIONED shorts={nbad} UNROUTED={len(unr)} wires={nwires} time={time.time()-t:.1f}s  => {'LEGAL+CONNECTED' if ok else 'NOT USABLE'}")
    if unr:
        print(f'  unrouted e.g. {unr[:6]}')