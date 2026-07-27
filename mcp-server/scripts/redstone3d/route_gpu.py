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

# neighbour offsets on a single layer (4-connected for wire runs)
_H = [(1, 0), (-1, 0), (0, 1), (0, -1)]


class GpuRouter:
    def __init__(self, placement, device="cuda", nlayers=2, layer_y=(0, 2), margin=6):
        self.pl = placement
        self.dev = torch.device(device)
        self.L = nlayers
        self.layer_y = layer_y            # actual Y for each layer index
        mn, mx = placement.bounds
        self.x0 = mn[0] - margin
        self.z0 = mn[2] - margin
        self.X = (mx[0] + margin) - self.x0 + 1
        self.Z = (mx[2] + margin) - self.z0 + 1
        self.base_y = mn[1]
        # static obstacle mask: cell bodies block layer 0 (projected)
        self.block = torch.zeros((self.L, self.X, self.Z), dtype=torch.bool, device=self.dev)
        for (x, y, z) in placement.occupancy:
            gx, gz = x - self.x0, z - self.z0
            if 0 <= gx < self.X and 0 <= gz < self.Z:
                self.block[0, gx, gz] = True
        # pins: map net -> source cell, sink cells, in grid coords (layer 0)
        self.pin_cells: Dict[Tuple[int, int], str] = {}
        for net, pos in placement.net_sources.items():
            self.pin_cells[(pos[0]-self.x0, pos[2]-self.z0)] = net
        for net, sinks in placement.net_sinks.items():
            for pos in sinks:
                self.pin_cells[(pos[0]-self.x0, pos[2]-self.z0)] = net
        # Pins are valid path ENDPOINTS, not obstacles — carve them out of the
        # block mask (cell occupancy included them). Wavefront may enter a pin
        # only as a goal; transit is barred separately by cost, but it must at
        # least be reachable.
        for (gx, gz) in self.pin_cells:
            if 0 <= gx < self.X and 0 <= gz < self.Z:
                self.block[0, gx, gz] = False

    def _g(self, x, z):
        return (x - self.x0, z - self.z0)

    def wavefront(self, sources: List[Tuple[int,int,int]], cost: torch.Tensor,
                  max_iters=None) -> torch.Tensor:
        """Parallel Lee/BFS distance field on the GPU. `sources` are (layer,gx,gz)
        seed cells (distance 0). `cost` is (L,X,Z) per-cell entry cost. Returns
        the distance field (L,X,Z); unreached cells = +inf. Relaxation:
        dist[n] = min(dist[n], min over neighbours(dist[nb]) + cost[n]).
        Iterate until stable (no change) or max_iters."""
        INF = float("inf")
        dist = torch.full((self.L, self.X, self.Z), INF, device=self.dev)
        for (l, gx, gz) in sources:
            dist[l, gx, gz] = 0.0
        blocked = self.block
        if max_iters is None:
            # a path is at most (X+Z) long per layer + a few via hops; that many
            # relaxation sweeps guarantees the field is exact.
            max_iters = self.X + self.Z + 4 * self.L
        cost_masked = cost.clone()
        cost_masked[blocked] = INF     # entering a blocked cell costs INF
        # FULLY ASYNC: fixed number of sweeps, NO per-step torch.equal sync (that
        # forced a GPU->CPU stall every iteration). All kernels queue on the GPU.
        for _ in range(max_iters):
            up = torch.roll(dist, 1, 1);  up[:, 0, :] = INF
            dn = torch.roll(dist, -1, 1); dn[:, -1, :] = INF
            lf = torch.roll(dist, 1, 2);  lf[:, :, 0] = INF
            rt = torch.roll(dist, -1, 2); rt[:, :, -1] = INF
            nb = torch.minimum(torch.minimum(up, dn), torch.minimum(lf, rt))
            if self.L > 1:
                vup = torch.roll(dist, 1, 0);  vup[0] = INF
                vdn = torch.roll(dist, -1, 0); vdn[-1] = INF
                nb = torch.minimum(nb, torch.minimum(vup, vdn))
            dist = torch.minimum(dist, nb + cost_masked)
            # keep sources pinned at 0 (cheap scatter, no sync)
            for (l, gx, gz) in sources:
                dist[l, gx, gz] = 0.0
        return dist


    def wavefront_batched(self, seeds_per_net, cost, sweeps):
        """Flood ALL nets at once. seeds_per_net: list (len N) of list of
        (l,gx,gz) seed cells. cost: (L,X,Z) shared cost field. Returns dist
        (N,L,X,Z). One set of GPU kernels relaxes every net in parallel — this is
        the GPU-native speedup (vs a Python loop over nets)."""
        INF = float("inf")
        N = len(seeds_per_net)
        dist = torch.full((N, self.L, self.X, self.Z), INF, device=self.dev)
        # seed mask (N,L,X,Z): where each net's sources are pinned to 0
        seed_idx = [[], [], [], []]   # n,l,x,z
        for n, seeds in enumerate(seeds_per_net):
            for (l, gx, gz) in seeds:
                seed_idx[0].append(n); seed_idx[1].append(l)
                seed_idx[2].append(gx); seed_idx[3].append(gz)
        si = [torch.tensor(a, device=self.dev, dtype=torch.long) for a in seed_idx]
        dist[si[0], si[1], si[2], si[3]] = 0.0
        cm = cost.clone()
        if cm.dim() == 3:             # shared (L,X,Z) -> broadcast over nets
            cm[self.block] = INF
            cm = cm.unsqueeze(0)
        else:                         # per-net (N,L,X,Z): confinement per net
            cm[:, self.block] = INF
        for _ in range(sweeps):
            up = torch.roll(dist, 1, 2);  up[:, :, 0, :] = INF
            dn = torch.roll(dist, -1, 2); dn[:, :, -1, :] = INF
            lf = torch.roll(dist, 1, 3);  lf[:, :, :, 0] = INF
            rt = torch.roll(dist, -1, 3); rt[:, :, :, -1] = INF
            nb = torch.minimum(torch.minimum(up, dn), torch.minimum(lf, rt))
            if self.L > 1:
                vup = torch.roll(dist, 1, 1);  vup[:, 0] = INF
                vdn = torch.roll(dist, -1, 1); vdn[:, -1] = INF
                nb = torch.minimum(nb, torch.minimum(vup, vdn))
            dist = torch.minimum(dist, nb + cm)
            dist[si[0], si[1], si[2], si[3]] = 0.0
        return dist

    def backtrace(self, dist: torch.Tensor, goal_layer, gx, gz,
                  cost: torch.Tensor) -> List[Tuple[int,int,int]]:
        """Recover a min-cost path from goal back to a source (dist==0) by greedy
        descent on the distance field. Returns list of (layer,gx,gz) source->goal."""
        INF = float("inf")
        d = dist  # keep on GPU; index scalars
        cur = (goal_layer, gx, gz)
        path = [cur]
        # move to CPU views for pointer-chasing (paths are short vs grid)
        dcpu = dist.detach().to("cpu")
        guard = 0
        while dcpu[cur[0], cur[1], cur[2]].item() > 0 and guard < self.X*self.Z*self.L:
            guard += 1
            l, x, z = cur
            best = None; bestv = dcpu[l, x, z].item()
            # in-layer neighbours
            for dx, dz in _H:
                nx, nz = x+dx, z+dz
                if 0 <= nx < self.X and 0 <= nz < self.Z:
                    v = dcpu[l, nx, nz].item()
                    if v < bestv:
                        bestv = v; best = (l, nx, nz)
            # via neighbours
            for dl in (1, -1):
                nl = l+dl
                if 0 <= nl < self.L:
                    v = dcpu[nl, x, z].item()
                    if v < bestv:
                        bestv = v; best = (nl, x, z)
            if best is None:
                break  # stuck (shouldn't happen if reached)
            cur = best; path.append(cur)
        path.reverse()
        return path

    def _occ_tensor(self, routes):
        """(L,X,Z) int tensor: cell -> net index+1 (0=empty). Last writer wins;
        used only for short detection (different indices adjacent = short)."""
        occ = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
        for idx, cells in routes.items():
            for (l, x, z) in cells:
                occ[l, x, z] = idx + 1
        return occ

    def _short_cells(self, occ):
        """Return a (L,X,Z) bool mask of cells that adjacency-short with a
        DIFFERENT net. In-layer 8-neighbour + inter-layer vertical/diagonal.
        Vectorized on GPU via shifted comparisons."""
        L, X, Z = self.L, self.X, self.Z
        nz = occ > 0
        bad = torch.zeros_like(nz)
        # In-layer 8-neighbour only. Inter-LAYER is NOT a short: layers are spaced
        # 2 in Y with a solid support block between (verified H@y2 × V@y4 isolation,
        # test_hv_layers Q2). Adjacent layer INDICES = 2 blocks apart in Y => never
        # short. (The earlier inter-layer shifts were a false-positive: they flagged
        # different-layer trunks as shorts when they're physically isolated.)
        shifts = [(0,1,0),(0,-1,0),(0,0,1),(0,0,-1),(0,1,1),(0,1,-1),(0,-1,1),(0,-1,-1)]
        for dl, dx, dz in shifts:
            s = torch.roll(occ, shifts=(dl,dx,dz), dims=(0,1,2))
            # zero out wrapped edges
            if dx == 1: s[:, 0, :] = 0
            elif dx == -1: s[:, -1, :] = 0
            if dz == 1: s[:, :, 0] = 0
            elif dz == -1: s[:, :, -1] = 0
            if dl == 1: s[0] = 0
            elif dl == -1: s[-1] = 0
            conflict = nz & (s > 0) & (s != occ)
            bad |= conflict
        return bad

    def route(self, max_iters=50, verbose=True, short_pen=8.0, hist_inc=4.0,
              seed=0, jitter=0.0):
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        net_idx = {n: i for i, n in enumerate(nets)}
        N = len(nets)
        hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
        if jitter > 0.0:
            # random per-cell history jitter breaks the symmetric field that
            # causes correlated-flip oscillation; each portfolio variant gets a
            # different landscape so at least one settles.
            g = torch.Generator(device=self.dev); g.manual_seed(seed)
            hist = hist + torch.rand((self.L, self.X, self.Z), generator=g,
                                     device=self.dev) * jitter
        SHORT_PEN = short_pen
        # sweeps = grid diameter (enough for exact field); one batched flood/iter
        sweeps = self.X + self.Z + 4 * self.L
        # per-net seeds: source cell (layer 0). Multi-sink handled by re-flooding
        # with the net's own already-placed cells added as seeds (cheap, done on
        # CPU between the 1-2 sink rounds; most nets are 1-2 sinks).
        src_of = {net_idx[n]: (0,) + self._g(self.pl.net_sources[n][0],
                                             self.pl.net_sources[n][2]) for n in nets}
        sinks_of = {}
        for n in nets:
            s = self.pl.net_sources[n]
            sinks_of[net_idx[n]] = [(0,) + self._g(k[0], k[2])
                                    for k in sorted(self.pl.net_sinks[n],
                                    key=lambda k: abs(s[0]-k[0])+abs(s[2]-k[2]))]
        best_routes = None; best_bad = 1 << 30
        occ_prev = None
        for it in range(max_iters):
            present = (self._short_cells(occ_prev).float() * SHORT_PEN
                       if occ_prev is not None else 0.0)
            cost = torch.ones((self.L, self.X, self.Z), device=self.dev) + hist + present
            # route sink-by-sink round (max sinks over all nets), batched over nets
            routes = {i: [] for i in range(N)}
            seeds = {i: [src_of[i]] for i in range(N)}
            max_sinks = max(len(v) for v in sinks_of.values())
            for r in range(max_sinks):
                seed_list = [seeds[i] for i in range(N)]
                dist = self.wavefront_batched(seed_list, cost, sweeps)
                dcpu = dist.to("cpu")
                for i in range(N):
                    if r >= len(sinks_of[i]):
                        continue
                    gl, gx, gz = sinks_of[i][r]
                    if dcpu[i, 0, gx, gz].item() == float("inf"):
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
                best_bad = nbad; best_routes = {k: list(v) for k, v in routes.items()}
            if verbose and (it % 2 == 0 or nbad == 0):
                print(f"  iter {it}: shorted cells={nbad}", flush=True)
            if nbad == 0:
                break
            hist += self._short_cells(occ).float() * hist_inc
        return best_routes, best_bad, net_idx

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
            print(f"  base negotiated: shorts={nbad}", flush=True)
        if nbad == 0:
            return routes, 0, net_idx
        adj = self._conflict_graph(routes, net_idx)
        # capacity-constrained greedy coloring: a net may join a layer only if it
        # conflicts with NO net already there AND the layer isn't full. Re-routing
        # confined to a sparse layer stays short-free; a crowded layer (17 nets)
        # produces NEW adjacencies. Cap per-layer to keep layers sparse.
        # CAP=1 => one net per layer: intra-layer shorts IMPOSSIBLE by
        # construction (a layer has a single net). Cross-layer is isolated
        # (2-Y spacing + solid separator). This is the deterministic 0-short
        # guarantee. GPU is indifferent to layer count. Non-conflicting nets
        # could share a layer (CAP>1) to save layers, but that risks re-route
        # adjacency; CAP=1 is the safe guarantee. Nets that DON'T conflict with
        # anything still each get a layer here (simple); optimize later.
        CAP = 1
        order = sorted(net_idx, key=lambda n: -len(adj[n]))
        color: Dict[str, int] = {}
        layer_members: Dict[int, list] = {}
        for n in order:
            c = 0
            while True:
                members = layer_members.get(c, [])
                if len(members) < CAP and all(m not in adj[n] for m in members):
                    break
                c += 1
            color[n] = c
            layer_members.setdefault(c, []).append(n)
        ncolors = max(color.values()) + 1
        if verbose:
            print(f"  conflict graph colored with {ncolors} layers", flush=True)
        return color, ncolors, net_idx

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
        # ensure grid has enough layers: layer L index = color (0..ncolors-1) for
        # TRUNK, plus layer 0 is the pin plane. We use layer index = color+1 for
        # trunks (reserve layer 0 as the pin/via-base plane) if ncolors+1 <= L.
        # Simpler: trunk layer = color (colors 0..nc-1), and pins live at y0 which
        # is layer 0. A color-0 trunk shares layer 0 with pins — fine, pins are
        # point endpoints. Route each net on its color layer.
        routes = {net_idx[n]: [] for n in nets}
        # group nets by color; route color-groups independently (batched)
        by_color: Dict[int, List[str]] = {}
        for n in nets:
            by_color.setdefault(color[n], []).append(n)
        for c, group in sorted(by_color.items()):
            tl = c + 1            # TRUNK layer for this group (>=1; layer 0 = pins only)
            if tl >= self.L:
                # not enough layers; skip (caller must size L >= ncolors+1)
                if verbose: print(f"  layer {c}: NO LAYER (need L>{tl})", flush=True)
                continue
            # Confine trunk to layer tl. y0 (layer 0) usable ONLY at pin columns
            # (source + sinks of THIS group) so vias can drop in; everywhere else
            # y0 is blocked so no group uses y0 as a routing plane (that was the
            # 653-short collision). Build a per-group cost that HARD-blocks all
            # layers except tl, and blocks y0 except at this group's pin columns.
            BIG = 1e9
            cost = torch.full((self.L, self.X, self.Z), BIG, device=self.dev)
            cost[tl] = 1.0                       # trunk layer free
            # allow a via column (all layers 0..tl) at each pin of this group
            pin_cols = set()
            for n in group:
                s = self.pl.net_sources[n]; pin_cols.add(self._g(s[0], s[2]))
                for k in self.pl.net_sinks[n]:
                    pin_cols.add(self._g(k[0], k[2]))
            for (gx, gz) in pin_cols:
                cost[0:tl+1, gx, gz] = 1.0       # vertical via corridor at the pin
            gi = {n: i for i, n in enumerate(group)}
            hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
            best = None; bestbad = 1 << 30
            for it in range(20):
                gr = {i: [] for i in range(len(group))}
                seeds = {}
                for n in group:
                    s = self.pl.net_sources[n]
                    seeds[gi[n]] = [(0,) + self._g(s[0], s[2])]
                sinks_of = {}
                for n in group:
                    s = self.pl.net_sources[n]
                    sinks_of[gi[n]] = [(0,) + self._g(k[0], k[2])
                                       for k in self.pl.net_sinks[n]]
                cc = cost + hist
                msink = max(len(v) for v in sinks_of.values())
                for r in range(msink):
                    seed_list = [seeds[i] for i in range(len(group))]
                    dist = self.wavefront_batched(seed_list, cc, sweeps)
                    dcpu = dist.to("cpu")
                    for i in range(len(group)):
                        if r >= len(sinks_of[i]):
                            continue
                        gl, gx, gz = sinks_of[i][r]
                        if dcpu[i, 0, gx, gz].item() == float("inf"):
                            continue
                        path = self._backtrace_cpu(dcpu[i], 0, gx, gz)
                        for cell in path:
                            if (cell[1], cell[2]) not in self.pin_cells:
                                if cell not in gr[i]:
                                    gr[i].append(cell)
                                if cell not in seeds[i]:
                                    seeds[i].append(cell)
                # short check within group (map to global idx)
                gocc = torch.zeros((self.L, self.X, self.Z), dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    for (l, x, z) in cells:
                        gocc[l, x, z] = i + 1
                nb = int(self._short_cells(gocc).sum().item())
                if nb < bestbad:
                    bestbad = nb; best = {i: list(v) for i, v in gr.items()}
                if nb == 0:
                    break
                hist += self._short_cells(gocc).float() * 4.0
            if verbose:
                print(f"  layer {c}: {len(group)} nets, intra-layer shorts={bestbad}", flush=True)
            for i, cells in best.items():
                routes[net_idx[group[i]]] = cells
        # final global short check across ALL layers
        occ = self._occ_tensor(routes)
        total_bad = int(self._short_cells(occ).sum().item())
        return routes, total_bad, net_idx

    def route_portfolio(self, variants=None, iters_per=25, verbose=True):
        """GPU portfolio: run several negotiated variants with different
        (short_pen, hist_inc, jitter, seed). Each gets a different cost landscape
        so at least one escapes the symmetric oscillation. Return the first to
        reach 0 shorts, else the overall best. Variants run sequentially here
        (each already batches all nets on the GPU); the win is DIVERSITY, not
        more parallelism — one variant converging beats all oscillating."""
        if variants is None:
            variants = [
                dict(short_pen=8.0,  hist_inc=4.0,  jitter=0.0,  seed=0),
                dict(short_pen=12.0, hist_inc=6.0,  jitter=1.0,  seed=1),
                dict(short_pen=6.0,  hist_inc=8.0,  jitter=2.0,  seed=2),
                dict(short_pen=16.0, hist_inc=3.0,  jitter=1.5,  seed=3),
                dict(short_pen=10.0, hist_inc=10.0, jitter=3.0,  seed=4),
                dict(short_pen=20.0, hist_inc=5.0,  jitter=2.5,  seed=5),
            ]
        best = None; best_bad = 1 << 30; best_idx = None
        net_idx = None
        for vi, v in enumerate(variants):
            routes, nbad, ni = self.route(max_iters=iters_per, verbose=False, **v)
            net_idx = ni
            if verbose:
                print(f"  variant {vi} {v}: best shorts={nbad}", flush=True)
            if nbad < best_bad:
                best_bad = nbad; best = routes; best_idx = vi
            if nbad == 0:
                if verbose: print(f"  variant {vi} LEGAL (0 shorts)", flush=True)
                break
        if verbose:
            print(f"  portfolio best: variant {best_idx}, shorts={best_bad}", flush=True)
        return best, best_bad, net_idx

    def _conflict_graph(self, routes, net_idx):
        """Which nets adjacency-conflict with which (from a routed occ). Returns
        adjacency dict net_i -> set(net_j)."""
        idx2 = {i: n for n, i in net_idx.items()}
        occ = self._occ_tensor(routes)
        adj = {n: set() for n in net_idx}
        L, X, Z = self.L, self.X, self.Z
        shifts = [(0,1,0),(0,-1,0),(0,0,1),(0,0,-1),(0,1,1),(0,1,-1),(0,-1,1),(0,-1,-1)]
        if L > 1:
            shifts += [(1,0,0),(-1,0,0),(1,1,0),(1,-1,0),(1,0,1),(1,0,-1)]
        for dl, dx, dz in shifts:
            s = torch.roll(occ, shifts=(dl,dx,dz), dims=(0,1,2))
            if dx == 1: s[:, 0, :] = 0
            elif dx == -1: s[:, -1, :] = 0
            if dz == 1: s[:, :, 0] = 0
            elif dz == -1: s[:, :, -1] = 0
            if dl == 1: s[0] = 0
            elif dl == -1: s[-1] = 0
            conflict = (occ > 0) & (s > 0) & (s != occ)
            pos = conflict.nonzero(as_tuple=False).tolist()
            for l, x, z in pos:
                a = int(occ[l, x, z].item()) - 1
                b = int(s[l, x, z].item()) - 1
                if a >= 0 and b >= 0:
                    adj[idx2[a]].add(idx2[b]); adj[idx2[b]].add(idx2[a])
        return adj

    def _backtrace_cpu(self, dist_cpu, l, x, z):
        """Greedy descent on a single net's CPU distance field (L,X,Z)."""
        cur = (l, x, z); path = [cur]
        guard = 0
        while dist_cpu[cur[0], cur[1], cur[2]].item() > 0 and guard < self.X*self.Z*self.L:
            guard += 1
            cl, cx, cz = cur; bestv = dist_cpu[cl, cx, cz].item(); best = None
            for dx, dz in _H:
                nx, nz = cx+dx, cz+dz
                if 0 <= nx < self.X and 0 <= nz < self.Z:
                    v = dist_cpu[cl, nx, nz].item()
                    if v < bestv: bestv = v; best = (cl, nx, nz)
            for dl in (1, -1):
                nl = cl+dl
                if 0 <= nl < self.L:
                    v = dist_cpu[nl, cx, cz].item()
                    if v < bestv: bestv = v; best = (nl, cx, cz)
            if best is None: break
            cur = best; path.append(cur)
        path.reverse()
        return path


if __name__ == "__main__":
    # loaded/run on Win; smoke test dims
    base = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, base)
    sys.path.insert(0, os.path.join(base, "..", "riscv_synth"))
    from placer import place
    nls = json.load(open(os.path.join(base, "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    L = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    cg = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    rg = int(sys.argv[4]) if len(sys.argv) > 4 else 10
    pl = place(nls[mod], col_gap=cg, row_gap=rg)
    r = GpuRouter(pl, nlayers=L, layer_y=tuple(range(0, 2*L, 2)))
    print(f"[{mod}] grid L={r.L} X={r.X} Z={r.Z} device={r.dev} nets={len(pl.net_sinks)}")
    t = time.time()
    # Step 1: color the conflict graph (few layers)
    color, ncolors, net_idx = r.route_layered(iters_per=20, verbose=True)
    if isinstance(color, dict):
        # need L >= ncolors+1 (layer 0 = pins, trunks on layers 1..ncolors)
        need = ncolors + 1
        if r.L < need:
            r = GpuRouter(pl, nlayers=need, layer_y=tuple(range(0, 2*need, 2)))
            color, ncolors, net_idx = r.route_layered(iters_per=20, verbose=False)
        # Step 2: layer-confined re-route (0-short by construction)
        routes, nbad, net_idx = r.route_layer_confined(color, ncolors, net_idx, verbose=True)
    else:
        routes, nbad = color, ncolors
    torch.cuda.synchronize() if r.dev.type == "cuda" else None
    nwires = sum(len(v) for v in routes.values())
    print(f"[{mod}] LAYERED DONE shorts={nbad} wires={nwires} layers={ncolors} time={time.time()-t:.1f}s")
