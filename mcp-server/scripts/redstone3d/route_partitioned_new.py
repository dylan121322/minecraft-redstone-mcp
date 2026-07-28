    # ========== Spatial Partition Routing (ROUTER_JOURNAL IX) ==========
    def route_partitioned(self, zone_width=80, base_iters=12, layer_iters=20,
                          verbose=True):
        """Spatial-zone layered routing. See ROUTER_JOURNAL §IX for design."""
        nets = list(self.pl.net_sinks)
        mn, mx = self.pl.bounds
        X0 = mn[0]

        def pin_xs(n):
            return [self.pl.net_sources[n][0]] + \
                   [k[0] for k in self.pl.net_sinks[n]]
        def zone_of(n):
            xs = pin_xs(n)
            return set((x - X0) // zone_width for x in xs)

        # 1. Base negotiated routing -> conflict graph
        v = dict(short_pen=12.0, hist_inc=3.0, jitter=1.0, seed=0)
        routes0, nbad0, net_idx = self.route(max_iters=base_iters, verbose=False, **v)
        idx2net = {i: n for n, i in net_idx.items()}
        adj = self._conflict_graph(routes0, net_idx)

        # 2. Classify nets
        local_nets = [n for n in nets if len(zone_of(n)) == 1]
        global_nets = [n for n in nets if len(zone_of(n)) > 1]
        if verbose:
            print(f"  zone_w={zone_width}: local={len(local_nets)} "
                  f"global={len(global_nets)}", flush=True)
        local_zones = {}
        for n in local_nets:
            z = list(zone_of(n))[0]
            local_zones.setdefault(z, []).append(n)
        if verbose:
            print(f"  local zones: "
                  f"{dict((z,len(g)) for z,g in sorted(local_zones.items()))}",
                  flush=True)

        # 3. Color each zone locally; reuse layer numbers across zones
        zone_local_color = {}
        max_local = 0
        for z, group in sorted(local_zones.items()):
            adj_sub = {n: adj[n] & set(group) for n in group}
            order = sorted(group, key=lambda n: -len(adj_sub[n]))
            local_col = {}
            for n in order:
                used = {local_col[m] for m in (adj_sub[n]) if m in local_col}
                c = 1
                while c in used:
                    c += 1
                local_col[n] = c
                zone_local_color[n] = (z, c)
            layers = max(local_col.values()) if local_col else 0
            max_local = max(max_local, layers)
            if verbose:
                print(f"  zone {z}: {len(group)} nets, {layers} layers",
                      flush=True)

        # 4 & 5. Route each zone's local layers independently, then global nets.
        routes_final = {net_idx[n]: [] for n in nets}
        sweeps = self.X + self.Z + 4 * self.L
        placed_occ = None
        INF = float("inf")

        def build_cost(tl, x_lo, x_hi, pin_set):
            cost = torch.full((self.L, self.X, self.Z), INF, device=self.dev)
            cost[tl] = 1.0
            if x_lo is not None:
                gx_lo = x_lo - self.x0
                gx_hi = min(x_hi - self.x0, self.X)
                cost[tl, :max(0, gx_lo), :] = INF
                cost[tl, gx_hi:, :] = INF
            for (gx, gz) in pin_set:
                cost[0:tl+1, gx, gz] = 1.0
            if placed_occ is not None:
                foreign = (placed_occ > 0)
                keep = foreign.clone()
                for dx, dz in [(1,0),(-1,0),(0,1),(0,-1)]:
                    s = torch.roll(foreign, shifts=(dx,dz), dims=(1,2))
                    if dx == 1: s[:, 0, :] = False
                    elif dx == -1: s[:, -1, :] = False
                    if dz == 1: s[:, :, 0] = False
                    elif dz == -1: s[:, :, -1] = False
                    keep |= s
                cost[tl][keep[tl]] = INF
            return cost

        def route_group(group, cost):
            gi = {n: i for i, n in enumerate(group)}
            hist = torch.zeros((self.L, self.X, self.Z), device=self.dev)
            best_gr = None; bestbad = 1 << 30
            for it in range(layer_iters):
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
                        if dcpu[i, 0, gx, gz].item() == INF:
                            continue
                        path = self._backtrace_cpu(dcpu[i], 0, gx, gz)
                        for cell in path:
                            is_pin = (cell[0] == 0 and
                                      (cell[1], cell[2]) in self.pin_cells)
                            if not is_pin:
                                if cell not in gr[i]:
                                    gr[i].append(cell)
                                if cell not in seeds[i]:
                                    seeds[i].append(cell)
                gocc = torch.zeros((self.L, self.X, self.Z),
                                   dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    for (l, x, z) in cells:
                        gocc[l, x, z] = i + 1
                nb = int(self._short_cells(gocc).sum().item())
                if nb < bestbad:
                    bestbad = nb; best_gr = {i: list(v) for i, v in gr.items()}
                if nb == 0:
                    break
                hist += self._short_cells(gocc).float() * 4.0
            return best_gr, bestbad

        for z, local_group in sorted(local_zones.items()):
            by_lc = {}
            for n in local_group:
                _, lc = zone_local_color[n]
                by_lc.setdefault(lc, []).append(n)
            for lc, group in sorted(by_lc.items()):
                pin_set = set()
                for n in group:
                    pin_set.add((self.pl.net_sources[n][0]-self.x0,
                                 self.pl.net_sources[n][2]-self.z0))
                    for k in self.pl.net_sinks[n]:
                        pin_set.add((k[0]-self.x0, k[2]-self.z0))
                x_lo = X0 + z * zone_width
                x_hi = x_lo + zone_width
                cost = build_cost(lc, x_lo, x_hi, pin_set)
                gr, bestbad = route_group(group, cost)
                if verbose:
                    print(f"  zone={z} lc={lc}: {len(group)} nets, "
                          f"shorts={bestbad}", flush=True)
                for i, cells in gr.items():
                    routes_final[net_idx[group[i]]] = cells
                if placed_occ is None:
                    placed_occ = torch.zeros((self.L, self.X, self.Z),
                                             dtype=torch.int32, device=self.dev)
                for i, cells in gr.items():
                    gidx = net_idx[group[i]] + 1
                    for (l, x, z) in cells:
                        placed_occ[l, x, z] = gidx

        for gi, n in enumerate(global_nets):
            tl = max_local + gi + 1
            if tl >= self.L:
                continue
            pin_set = set()
            pin_set.add((self.pl.net_sources[n][0]-self.x0,
                         self.pl.net_sources[n][2]-self.z0))
            for k in self.pl.net_sinks[n]:
                pin_set.add((k[0]-self.x0, k[2]-self.z0))
            cost = build_cost(tl, None, None, pin_set)
            gr, bestbad = route_group([n], cost)
            if verbose:
                print(f"  global {n} tl={tl}: shorts={bestbad}", flush=True)
            if 0 in gr:
                routes_final[net_idx[n]] = gr[0]
            if placed_occ is None:
                placed_occ = torch.zeros((self.L, self.X, self.Z),
                                         dtype=torch.int32, device=self.dev)
            if 0 in gr:
                for (l, x, z) in gr[0]:
                    placed_occ[l, x, z] = net_idx[n] + 1

        # Final checks
        occ = self._occ_tensor(routes_final)
        nbad = int(self._short_cells(occ).sum().item())
        unrouted = []
        for n, i in net_idx.items():
            cells = routes_final.get(i, [])
            if not cells:
                unrouted.append((n, "empty")); continue
            S = set((c[0], c[1], c[2]) for c in cells)
            if len(set(c[0] for c in cells)) < 2:
                # tl=1: trunk is directly above pins, no intermediate via needed.
                # Only flag if the pin itself has no adjacent trunk cell either.
                pass  # fall through to near-check below
            sg = self._g(self.pl.net_sources[n][0], self.pl.net_sources[n][2])
            near = lambda g: any((1, g[0]+dx, g[1]+dz) in S
                                 for dx, dz in [(0,0),(1,0),(-1,0),(0,1),(0,-1)])
            if not near(sg):
                unrouted.append((n, "src-open")); continue
            for k in self.pl.net_sinks[n]:
                if not near(self._g(k[0], k[2])):
                    unrouted.append((n, "sink-open")); break
        self.unrouted = unrouted
        return routes_final, nbad, net_idx
