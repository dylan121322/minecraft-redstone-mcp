"""locate2.py — precise coordinates of target/observer/copper_bulb in a 1.18+
save by decoding the block_states compact array."""
import sys, os, zlib, struct, io

WANT = {"minecraft:target", "minecraft:observer", "minecraft:copper_bulb",
        "minecraft:copper_bulb[lit=true]", "minecraft:copper_bulb[lit=false]"}


def iter_chunks(path):
    f = open(path, "rb")
    hdr = f.read(4096)
    for i in range(1024):
        off = struct.unpack(">I", hdr[i * 4:i * 4 + 4])[0]
        if off == 0:
            continue
        f.seek((off >> 8) * 4096)
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
        yield raw
    f.close()


def scan_one(fname, path, from_nbt):
    found = []
    for raw in iter_chunks(path):
        try:
            chunk = from_nbt(raw)
        except Exception:
            continue
        try:
            cx = chunk["xPos"].value
            cz = chunk["zPos"].value
        except Exception:
            continue
        secs = chunk.get("sections") or []
        for sec in secs:
            try:
                sy = sec["Y"].value
                bs = sec["block_states"]
                pal = bs["palette"]
                arr = bs["data"]
            except Exception:
                continue
            names = [p["Name"].value for p in pal]
            if not any(n in WANT for n in names):
                continue
            bits = max(4, (len(pal) - 1).bit_length())
            mask = (1 << bits) - 1
            per_long = 64 // bits
            vals = list(arr.value)
            for i, idx in enumerate(names):
                if idx not in WANT:
                    continue
                for long_i, packed in enumerate(vals):
                    for sub in range(per_long):
                        pi = (packed >> (sub * bits)) & mask
                        if pi == i:
                            bi = long_i * per_long + sub
                            wx = cx * 16 + (bi & 15)
                            wy = sy * 16 + ((bi >> 4) & 15)
                            wz = cz * 16 + ((bi >> 8) & 15)
                            found.append((fname, wx, wy, wz, idx))
    return found


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Library/Application Support/minecraft/saves/cpu_mod")
    from nbt import nbt
    from_nbt = lambda raw: nbt.NBTFile(buffer=io.BytesIO(raw))
    region_dir = os.path.join(save, "region")
    found = []
    for fname in sorted(os.listdir(region_dir)):
        if not fname.endswith(".mca"):
            continue
        try:
            found += scan_one(fname, os.path.join(region_dir, fname), from_nbt)
        except Exception as e:
            print(f"  SKIP {fname}: {type(e).__name__}")
    print(f"located {len(found)} wanted blocks:")
    for f in found:
        print(f"  {f[4].split(':')[1]:20s} @ ({f[1]}, {f[2]}, {f[3]}) in {f[0]}")


if __name__ == "__main__":
    main()
