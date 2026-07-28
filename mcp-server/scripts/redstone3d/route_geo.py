"""
route_geo.py — GEOMETRY-LEVEL router: produces directly-buildable redstone
(real coords, via_gadget rise/drop) instead of abstract cells. Unifies route +
emit so the short-check runs on the actual geometry.

Design (all primitives MCHPRS-verified this session):
  - Cells at y=base. Each net: source pin (y0) -> horizontal RISE (via_gadget)
    to its trunk layer -> trunk run -> horizontal DROP to each sink pin (y0).
  - CAP=3 zone coloring gives SHALLOW trunk layers (reused across zones), so
    rises are short (<=~8 x). Trunk layers spaced 2 in Y (H/V isolation).
  - Occupancy is tracked on the real (x,y,z) grid; a placement that would put
    two different nets' dust in each other's short-shell is rejected/reported.
  - Repeater refresh: trunk start (after rise) + inside rise/drop every 10
    levels (via_gadget already inserts these). Non-inverting.

Output: {(x,y,z): block} + pi_inject + po_read, same as emit_full, for MCHPRS
verify and in-game build.
"""
import sys, os
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "riscv_synth"))
from via_gadget import rise_cells, drop_cells

W = "minecraft:redstone_wire"; S = "minecraft:stone"; RB = "minecraft:redstone_block"
def rep(f): return f"minecraft:repeater[facing={f},delay=1]"
_SHELL = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]


class GeoRouter:
    def __init__(self, placement, base_y=0, layer_gap=2):
        self.pl = placement
        self.base_y = base_y
        self.layer_gap = layer_gap          # Y between trunk layers
        self.blocks = {}                    # (x,y,z)->block
        self.owner = {}                     # (x,y,z)->net (dust cells only, for short-check)

    def _set(self, x, y, z, b, net=None):
        self.blocks[(x, y, z)] = b
        if b == W and net is not None:
            self.owner[(x, y, z)] = net

    def trunk_y(self, layer):
        return self.base_y + layer * self.layer_gap

    # -- conflict graph via a quick abstract pre-route (reuse GpuRouter's) --
    def color_zones(self, zone_width=80, cap=3):
        """Return net->(zone, local_color) and max local color. Uses a cheap
        conflict estimate: two nets conflict if their pin bounding boxes overlap
        in the same zone. (Good enough to spread same-region nets across layers.)"""
        nets = [n for n in self.pl.net_sinks
                if self.pl.net_sources.get(n) and self.pl.net_sinks.get(n)]
        mn = self.pl.bounds[0]; X0 = mn[0]
        def zone_of(n):
            xs = [self.pl.net_sources[n][0]] + [k[0] for k in self.pl.net_sinks[n]]
            return set((x - X0)//zone_width for x in xs)
        # z-extent per net (for conflict: same zone + overlapping z-range)
        def zext(n):
            zs = [self.pl.net_sources[n][2]] + [k[2] for k in self.pl.net_sinks[n]]
            return (min(zs), max(zs))
        local = [n for n in nets if len(zone_of(n)) == 1]
        glob = [n for n in nets if len(zone_of(n)) > 1]
        by_zone = defaultdict(list)
        for n in local:
            by_zone[list(zone_of(n))[0]].append(n)
        color = {}
        max_c = 0
        for zn, group in sorted(by_zone.items()):
            # greedy: assign smallest color whose members' z-ranges don't overlap
            # this net's z-range and layer isn't full (CAP)
            members = defaultdict(list)   # color -> list of (zlo,zhi)
            for n in sorted(group, key=lambda n: zext(n)[0]):
                lo, hi = zext(n)
                c = 1
                while True:
                    ms = members[c]
                    overlap = any(not (hi < a-1 or lo > b+1) for (a, b) in ms)
                    if len(ms) < cap and not overlap:
                        break
                    c += 1
                color[n] = (zn, c); members[c].append((lo, hi)); max_c = max(max_c, c)
        return color, max_c, glob, nets, X0, zone_width

    def route(self, zone_width=80, cap=3, verbose=True):
        color, max_c, glob, nets, X0, zw = self.color_zones(zone_width, cap)
        # global nets get layers above the local ones
        for gi, n in enumerate(glob):
            color[n] = (-1, max_c + 1 + gi)
        # 1. floor + cells
        mn, mx = self.pl.bounds
        # emit cells via a recorder adapter
        class Ad:
            def __init__(s, r): s.r = r
            def set_block_from_string(s, x, y, z, b): s.r._set(int(x), int(y), int(z), b)
        ad = Ad(self)
        for name, pc in self.pl.placed.items():
            pc.cell.emit(ad, *pc.origin)

        # 2. per-net geometry: source-rise -> trunk -> sink-drops
        unrouted = []
        for n in nets:
            zn, lc = color[n]
            tl = lc                          # trunk layer index (>=1)
            ty = self.trunk_y(tl)
            src = self.pl.net_sources[n]     # world (x,y,z), output pin (east)
            sx, sy, sz = src
            # RISE from source pin: source dust at (sx, base, sz), rise east
            self._set(sx, self.base_y, sz, W, n)
            pr, xo = rise_cells(sx, sz, self.base_y, ty)
            for (x, y, z, b) in pr:
                self._set(x, y, z, b, n)
            # repeater refresh + trunk start at xo+1
            self._set(xo, ty-1, sz, S)
            self._set(xo+1, ty-1, sz, S); self._set(xo+1, ty, sz, rep("west"))
            # trunk needs to reach each sink's x (minus drop width). Run trunk on
            # row sz from xo+2 east to the max sink x, then per-sink: drop.
            sinks = self.pl.net_sinks[n]
            trunk_x0 = xo + 2
            # trunk run to cover all sinks (drop starts drop_w before pin)
            max_px = max(k[0] for k in sinks)
            trunk_x1 = max_px + 2
            for x in range(trunk_x0, trunk_x1+1):
                self._set(x, ty, sz, W, n); self._set(x, ty-1, sz, S)
            # per sink: from trunk, drop to the sink pin. Sink pin (px,py,pz) reads
            # from west (px-1). Drop lands at (px-1, base). Need to also move in z
            # from sz to pz — do it on the trunk layer (horizontal), then drop.
            for k in sinks:
                px, py, pz = k
                # z-jog on trunk layer from sz to pz at x = px-? then drop
                # drop needs (ty-base) x-steps; start drop at px-1-(ty-self.base_y)
                dstart = px - 1 - (ty - self.base_y)
                # trunk z-jog at column dstart from sz to pz
                zlo, zhi = min(sz, pz), max(sz, pz)
                for zz in range(zlo, zhi+1):
                    self._set(dstart, ty, zz, W, n); self._set(dstart, ty-1, zz, S)
                # drop from (dstart, ty, pz) to (px-1, base, pz)
                pd, xo2 = drop_cells(dstart, pz, ty, self.base_y)
                for (x, y, z, b) in pd:
                    self._set(x, y, z, b, n)
                # feed pin: y0 dust at px-1
                self._set(px-1, self.base_y, pz, W, n)

        # 3. PI/PO
        pi = {}
        for net in [nn for nn in self.pl.primary_inputs]:
            p = self.pl.primary_inputs[net]
            pi[net] = [p[0]-1, p[1], p[2]]
        po = {net: list(self.pl.primary_outputs[net]) for net in self.pl.primary_outputs}

        # 4. short check on real geometry
        shorts = self._count_shorts()
        if verbose:
            print(f"  geo route: nets={len(nets)} global={len(glob)} "
                  f"max_layer={max(lc for _,lc in color.values())} "
                  f"blocks={len(self.blocks)} shorts={shorts}", flush=True)
        return self.blocks, pi, po, shorts

    def _count_shorts(self):
        sh = 0
        for (x, y, z), net in self.owner.items():
            for dx, dz in _SHELL:
                o = self.owner.get((x+dx, y, z+dz))
                if o is not None and o != net: sh += 1
            for dy in (1, -1):
                o = self.owner.get((x, y+dy, z))
                if o is not None and o != net: sh += 1
        return sh // 2


if __name__ == "__main__":
    import json
    from placer import place
    nls = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "riscv_synth", "netlists.json")))
    mod = sys.argv[1] if len(sys.argv) > 1 else "alu1"
    cg = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    rg = int(sys.argv[3]) if len(sys.argv) > 3 else 16
    pl = place(nls[mod], col_gap=cg, row_gap=rg)
    r = GeoRouter(pl)
    blocks, pi, po, shorts = r.route(zone_width=80, cap=3, verbose=True)
    xs=[k[0] for k in blocks]; ys=[k[1] for k in blocks]; zs=[k[2] for k in blocks]
    print(f"[{mod}] blocks={len(blocks)} bbox x[{min(xs)},{max(xs)}] "
          f"y[{min(ys)},{max(ys)}] z[{min(zs)},{max(zs)}] shorts={shorts}")
    out={"blocks":[[x,y,z,s] for (x,y,z),s in blocks.items()],
         "pi_inject":pi,"po_read":po,"module":mod}
    json.dump(out, open(rf"E:\project\{mod}_geo.json","w"))
    print(f"  saved {mod}_geo.json")
