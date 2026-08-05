"""
coupling.py — the MEASURED redstone coupling rule, in one place.

Every case below was measured in MCHPRS (riscv_build/test_physics_full.py) on a
flat /setblock build, driving one net and reading another:

  COUPLED                                             measured
    orthogonal dust-dust                              11
    diagonal dust-dust sharing an occupied orth cell  10
    dust on a block that a dust powers (ramp / strong) 11
    see-below: victim one level lower, one cell across 11
  ISOLATED
    pure diagonal, victim otherwise isolated           0
    dust directly above with no support block          0
    a dust diagonal to a block that a dust powers      0
    repeater sides                                     0
    beside a torch's mount (constant, drive-independent)
    two dust separated by a solid block                0
    two dust two cells apart on the same layer         0

Consequences for the router:
  * the old 8-neighbour shell is TOO STRICT (it rejects pure diagonals)
  * plain orthogonal-only is TOO LOOSE (it misses the shared-cell path, the
    ramp/strong-power path and see-below) — that is why relaxing to 4-neighbour
    produced real shorts on Mux2to1 (6) and ImmGen (3)

`couples(a, b, occ)` implements the full rule for two conductor voxels of
different nets, given the occupancy map.
"""

ORTH = [(1, 0), (-1, 0), (0, 1), (0, -1)]
DIAG = [(1, 1), (1, -1), (-1, 1), (-1, -1)]


def couples(a, b, occ):
    """True if conductors a and b (different nets) interfere. `occ` maps
    (x,y,z)->net for every conducting voxel; solid blocks are NOT in occ."""
    ax, ay, az = a
    bx, by, bz = b
    dx, dy, dz = bx - ax, by - ay, bz - az
    adx, ady, adz = abs(dx), abs(dy), abs(dz)

    # same layer
    if ady == 0:
        if adx + adz == 1:
            return True                      # P1 orthogonal
        if adx == 1 and adz == 1:
            # P3: diagonal couples only through a shared orthogonal conductor
            return ((ax + dx, ay, az) in occ) or ((ax, ay, az + dz) in occ)
        return False                         # P12 further apart

    # one level apart
    if ady == 1:
        if adx == 0 and adz == 0:
            # P4 measured ISOLATED without a support block; but a dust sitting on
            # a block that the lower dust powers IS coupled (P7). The support
            # block is not in occ, so treat the stacked case as coupled — being
            # conservative here costs little and P7/P4b showed 11.
            return True
        if adx + adz == 1:
            return True                      # P5/P4b ramp, P6 see-below
        return False                          # diagonal across a layer: isolated

    return False                              # 2+ layers apart


def shell_offsets():
    """Offsets that must be CHECKED as potential couplers (superset). The exact
    verdict still needs `couples`, because the diagonal cases are conditional."""
    out = [(dx, 0, dz) for dx, dz in ORTH + DIAG]
    out += [(0, 1, 0), (0, -1, 0)]
    out += [(dx, dy, dz) for dy in (1, -1) for dx, dz in ORTH]
    return out


def count_shorts(occ):
    """Count interfering pairs under the measured rule."""
    seen = set()
    offs = shell_offsets()
    for p, net in occ.items():
        for dx, dy, dz in offs:
            q = (p[0] + dx, p[1] + dy, p[2] + dz)
            o = occ.get(q)
            if o is None or o == net:
                continue
            if couples(p, q, occ):
                seen.add(tuple(sorted([p, q])))
    return len(seen)
