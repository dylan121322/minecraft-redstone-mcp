"""
locate_components.py — find the exact coordinates of target / observer / copper
bulb blocks in a save, so we can understand how they are wired.
"""
import sys, os, zlib, struct
from collections import Counter

WANT = {"minecraft:target", "minecraft:observer", "minecraft:copper_bulb",
        "minecraft:copper_bulb[lit=true]"}


def iter_chunks(path):
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
        if comp == 1:
            raw = zlib.decompress(data, 16 + zlib.MAX_WBITS)
        elif comp == 2:
            raw = zlib.decompress(data)
        elif comp == 3:
            raw = data
        else:
            continue
        yield i & 31, (i >> 5) & 31, raw, sect_off
    f.close()


def parse_nbt(raw):
    import io
    from nbt import nbt
    return nbt.NBTFile(buffer=io.BytesIO(raw))


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Library/Application Support/minecraft/saves/cpu_mod")
    region_dir = os.path.join(save, "region")
    found = []
    for fname in sorted(os.listdir(region_dir)):
        if not fname.endswith(".mca"):
            continue
        path = os.path.join(region_dir, fname)
        parts = fname.replace("r.", "").replace(".mca", "").split(".")
        rx, rz = int(parts[0]), int(parts[1])
        try:
            for lcx, lcz, raw, sect_off in iter_chunks(path):
                try:
                    chunk = parse_nbt(raw)
                except Exception:
                    continue
                try:
                    cx = chunk["xPos"].value
                    cz = chunk["zPos"].value
                except Exception:
                    cx = rx * 32 + lcx
                    cz = rz * 32 + lcz
                secs = chunk.get("sections") or []
                for sec in secs:
                    try:
                        sy = sec["Y"].value
                        bs = sec["block_states"]
                        pal = bs["palette"]
                        if "data" in bs:
                            arr = list(bs["data"].value) if hasattr(bs["data"], "value") else list(bs["data"])
                        else:
                            arr = None
                    except Exception:
                        continue
                    for pi, entry in enumerate(pal):
                        name = entry["Name"].value
                        if name not in WANT:
                            continue
                        # find which block positions use this palette index
                        if arr is None:
                            continue
                        bits = max(1, (len(pal) - 1).bit_length())
                        for blk_i, packed in enumerate(arr):
                            # extract palette index for this block
                            idx = (packed >> (blk_i * bits)) & ((1 << bits) - 1) \
                                if False else None
                            break
                        # simpler: just report the palette presence per section
                        found.append((fname, cx, cz, sy, name, pi))
        except Exception as e:
            print(f"  SKIP {fname}: {type(e).__name__}")
    print(f"found {len(found)} palette entries:")
    for f in found:
        print(f"  {f}")


if __name__ == "__main__":
    main()
