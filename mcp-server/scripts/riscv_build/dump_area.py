"""dump_area.py — dump the blocks around a coordinate as a 3D map, so the wiring
of a component (target/observer/etc) is visible. Usage: dump_area.py <save>
<wx> <wy> <wz> [radius]"""
import sys, os, zlib, struct, io

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


def main():
    save = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.expanduser("~/Library/Application Support/minecraft/saves/cpu_mod")
    wx, wy, wz = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    rad = int(sys.argv[5]) if len(sys.argv) > 5 else 4
    from nbt import nbt
    region_dir = os.path.join(save, "region")
    grid = {}
    for fname in sorted(os.listdir(region_dir)):
        if not fname.endswith(".mca"):
            continue
        for raw in iter_chunks(os.path.join(region_dir, fname)):
            try:
                chunk = nbt.NBTFile(buffer=io.BytesIO(raw))
                cx = chunk["xPos"].value; cz = chunk["zPos"].value
            except Exception:
                continue
            # only touch chunks overlapping the window
            if abs(cx * 16 - wx) > 16 or abs(cz * 16 - wz) > 16:
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
                if abs(sy * 16 - wy) > 16:
                    continue
                names = [p["Name"].value for p in pal]
                bits = max(4, (len(pal) - 1).bit_length())
                mask = (1 << bits) - 1
                per_long = 64 // bits
                vals = list(arr.value)
                for long_i, packed in enumerate(vals):
                    for sub in range(per_long):
                        pi = (packed >> (sub * bits)) & mask
                        bi = long_i * per_long + sub
                        bx = cx * 16 + (bi & 15)
                        by = sy * 16 + ((bi >> 4) & 15)
                        bz = cz * 16 + ((bi >> 8) & 15)
                        if abs(bx - wx) <= rad and abs(by - wy) <= rad \
                                and abs(bz - wz) <= rad:
                            grid[(bx, by, bz)] = names[pi]

    print(f"window around ({wx},{wy},{wz}) radius {rad}:")
    for dy in range(rad, -rad - 1, -1):
        print(f"\n  y={wy+dy}:")
        for dz in range(-rad, rad + 1):
            row = []
            for dx in range(-rad, rad + 1):
                b = grid.get((wx + dx, wy + dy, wz + dz))
                if not b:
                    row.append("......")
                    continue
                s = b.split(":")[1]
                tag = {"target": "TARGET", "observer": "OBSV",
                       "redstone_wire": "dust", "repeater": "REP",
                       "comparator": "CMP", "redstone_torch": "TORCH",
                       "redstone_block": "RBLCK", "stone": "stone",
                       "redstone_wall_torch": "wTCH"}.get(s, s[:5])
                row.append(f"{tag:>6s}")
            print(f"    z={wz+dz:+d} " + " | ".join(row))


if __name__ == "__main__":
    main()
