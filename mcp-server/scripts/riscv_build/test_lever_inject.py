"""
test_lever_inject.py — can one world be reused for many measurements?

The verifier currently rebuilds a ~30k-block world twice per net, which is why the
box sat at 40% CPU no matter how many workers were thrown at it: the cost is
single-threaded world construction, not a shortage of parallelism. MchprsWorld
exposes set_lever_power / set_signal_strength, so if a lever can drive a net's
source we can build the world ONCE and then flip inputs and re-tick per net.

Checks:
  L1  a lever drives an adjacent dust run (and releasing it clears the run)
  L2  set_lever_power + tick can be repeated on the same world, with the readings
      following each flip
  L3  two independent levers on one world drive their own runs without crosstalk
"""
import sys
sys.path.insert(0, "/Users/boqing/project/fundamentalLabs-minecraft-mcp/mcp-server/scripts/redstone3d")
import nucleation as nuc

S = "minecraft:stone"; W = "minecraff:redstone_wire".replace("ff", "ft")


def slab(B, x0, x1, z0, z1, y=-1):
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            B(x, y, z, S)


def build(levers, run_len=10):
    """One world with `levers` independent lever+dust runs at distinct z rows."""
    sc = nuc.Schematic.create("lev")
    B = sc.set_block_from_string
    slab(B, -4, run_len + 4, -2, 4 * levers + 4)
    ends = []
    for i in range(levers):
        z = 2 + i * 4
        B(0, 0, z, "minecraft:lever[face=floor,facing=north,powered=false]")
        for x in range(1, run_len + 1):
            B(x, 0, z, W)
        ends.append((run_len, 0, z))
    w = nuc.MchprsWorld.create_with_options(sc, True, False)
    return w, ends


if __name__ == "__main__":
    print("=== L1/L2: one world, lever flipped repeatedly ===")
    w, ends = build(1)
    for state in (False, True, False, True):
        w.set_lever_power(0, 0, 2, state)
        w.tick(10)
        print(f"  lever={str(state):5s} -> end power={w.get_redstone_power(*ends[0])}")

    print("\n=== L3: three levers on ONE world, no crosstalk ===")
    w, ends = build(3)
    import itertools
    for combo in itertools.product((False, True), repeat=3):
        for i, st in enumerate(combo):
            w.set_lever_power(0, 0, 2 + i * 4, st)
        w.tick(12)
        reads = [w.get_redstone_power(*e) for e in ends]
        exp = [15 if c else 0 for c in combo]
        ok = all((r > 0) == c for r, c in zip(reads, combo))
        print(f"  levers={combo} -> reads={reads}  {'ok' if ok else 'MISMATCH'}")
