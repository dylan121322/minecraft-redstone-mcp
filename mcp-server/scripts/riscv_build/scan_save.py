"""
scan_save.py — scan a Minecraft save for redstone component distribution,
focusing on the components that could change the build approach:
  target, copper_bulb, observer, and also the classic set.
Usage: python3 scan_save.py <path-to-save> [region-prefix-filter]
"""
import sys, os
from collections import Counter
import anvil

REDSTONE = [
    "minecraft:target", "minecraft:copper_bulb", "minecraft:observer",
    "minecraft:redstone_wire", "minecraft:repeater", "minecraft:comparator",
    "minecraft:redstone_torch", "minecraft:redstone_block",
    "minecraft:redstone_lamp", "minecraft:lever", "minecraft:hopper",
    "minecraft:piston", "minecraft:sticky_piston", "minecraft:dispenser",
    "minecraft:dropper", "minecraft:note_block", "minecraft:daylight_detector",
    "minecraft:tripwire_hook", "minecraft:redstone_wall_torch",
    "minecraft:copper_trapdoor", "minecraft:heavy_weighted_pressure_plate",
    "minecraft:light_weighted_pressure_plate", "minecraft:stone_pressure_plate",
    "minecraft:oak_pressure_plate",
]


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Library/Application Support/minecraft/saves/cpu_mod")
    region_dir = os.path.join(save, "region")
    if not os.path.isdir(region_dir):
        print(f"no region dir at {region_dir}")
        return
    files = sorted(os.listdir(region_dir))
    total = Counter()
    per_region = {}
    blocks_seen = Counter()
    for fname in files:
        if not fname.endswith(".mca"):
            continue
        path = os.path.join(region_dir, fname)
        try:
            r = anvil.Region.from_file(path)
        except Exception as e:
            print(f"  SKIP {fname}: {type(e).__name__}")
            continue
        local = Counter()
        nchunks = 0
        for cx in range(32):
            for cz in range(32):
                try:
                    chunk = r.get_chunk(cx, cz)
                except Exception:
                    continue
                if chunk is None:
                    continue
                nchunks += 1
                # walk all sections, all block states
                for sec in chunk.sections or []:
                    try:
                        palette = sec.block_palette
                    except Exception:
                        continue
                    names = [b.get("Name", "") if isinstance(b, dict) else str(b)
                             for b in palette]
                    # count palette usage by scanning blocks array (compacted)
                    try:
                        blocks = sec.block_states if hasattr(sec, "block_states") \
                            else getattr(sec, "blocks", None)
                    except Exception:
                        blocks = None
                    for i, name in enumerate(names):
                        if name in REDSTONE:
                            local[name] += 1  # presence per palette entry
                            total[name] += 1
                            blocks_seen[name] += 1
        per_region[fname] = dict(local)
    print(f"scanned {len(files)} region files")
    print(f"\n=== redstone components in '{os.path.basename(save)}' ===")
    for name, cnt in total.most_common():
        print(f"  {name.split(':')[1]:30s} {cnt:8d}")
    # target/copper_bulb/observer locations
    print("\n=== key components per region ===")
    for fname, d in per_region.items():
        interesting = {k: v for k, v in d.items()
                       if k in ("minecraft:target", "minecraft:copper_bulb",
                                "minecraft:observer")}
        if interesting:
            print(f"  {fname}: {interesting}")


if __name__ == "__main__":
    main()
