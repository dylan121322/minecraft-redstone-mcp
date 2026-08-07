"""
scan_save2.py — scan a 1.18+ save (no Level wrapper) for redstone components.
Reads region files directly with anvil's NBT layer, walking each chunk's
`block_states` palette.
"""
import sys, os, zlib, struct
from collections import Counter

REDSTONE = {
    "minecraft:target", "minecraft:copper_bulb", "minecraft:observer",
    "minecraft:redstone_wire", "minecraft:repeater", "minecraft:comparator",
    "minecraft:redstone_torch", "minecraft:redstone_block",
    "minecraft:redstone_lamp", "minecraft:lever", "minecraft:hopper",
    "minecraft:piston", "minecraft:sticky_piston", "minecraft:dispenser",
    "minecraft:dropper", "minecraft:note_block", "minecraft:daylight_detector",
    "minecraft:tripwire_hook", "minecraft:redstone_wall_torch",
    "minecraft:copper_trapdoor",
}


def read_palette_names(chunk_nbt):
    """Extract every palette entry name across all sections."""
    names = []
    secs = chunk_nbt.get("sections")
    if secs is None:
        return names
    for sec in secs:
        try:
            bs = sec["block_states"]
            pal = bs["palette"]
        except (KeyError, TypeError):
            continue
        for entry in pal:
            try:
                names.append(entry["Name"].value)
            except (KeyError, AttributeError):
                pass
    return names


def iter_chunks(path):
    """Yield raw NBT per chunk from a region file (1.18+ layout)."""
    f = open(path, "rb")
    hdr = f.read(4096)
    for i in range(1024):
        off = struct.unpack(">I", hdr[i * 4:i * 4 + 4])[0]
        if off == 0:
            continue
        sect_off = off >> 8
        f.seek(sect_off * 4096)
        ln = struct.unpack(">I", f.read(4))[0]
        comp = f.read(1)[0]
        data = f.read(ln - 1)
        if comp == 1:  # gzip
            raw = zlib.decompress(data, 16 + zlib.MAX_WBITS)
        elif comp == 2:  # zlib
            raw = zlib.decompress(data)
        elif comp == 3:  # none
            raw = data
        else:
            continue
        yield raw
    f.close()


def parse_nbt(raw):
    """Minimal NBT parser for chunk (1.18+): return dict of primitive tags and
    list-of-compounds. Only handles what we need."""
    from nbt import nbt
    import io
    return nbt.NBTFile(buffer=io.BytesIO(raw))


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Library/Application Support/minecraft/saves/cpu_mod")
    region_dir = os.path.join(save, "region")
    total = Counter()
    key_where = []
    files = sorted(os.listdir(region_dir))
    for fname in files:
        if not fname.endswith(".mca"):
            continue
        path = os.path.join(region_dir, fname)
        try:
            for raw in iter_chunks(path):
                try:
                    chunk = parse_nbt(raw)
                except Exception:
                    continue
                try:
                    names = read_palette_names(chunk)
                except Exception:
                    continue
                for nm in names:
                    if nm in REDSTONE:
                        total[nm] += 1
                        if nm in ("minecraft:target", "minecraft:copper_bulb",
                                  "minecraft:observer"):
                            key_where.append(fname)
        except Exception as e:
            print(f"  SKIP {fname}: {type(e).__name__}")
    print(f"scanned {len(files)} regions")
    print(f"\n=== redstone components in '{os.path.basename(save)}' ===")
    for name, cnt in total.most_common():
        print(f"  {name.split(':')[1]:30s} {cnt:8d}")
    print(f"\ntarget/copper_bulb/observer appear in {len(set(key_where))} regions")


if __name__ == "__main__":
    main()
