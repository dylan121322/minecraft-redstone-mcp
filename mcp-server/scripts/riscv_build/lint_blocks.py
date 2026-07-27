"""
lint_blocks.py — offline physical sanity check on an exported .blocks.json.
Catches the failure modes that made in-game builds not conduct, WITHOUT building:

  1. FLOATING_DUST: redstone_wire with no solid block directly below.
  2. TORCH_MOUNT_MISSING: wall_torch with no solid block on its attachment face.
  3. REPEATER_FEED: repeater whose input side isn't fed by a wire/source in-line,
     or whose output isn't consumed in-line (dangling).
  4. TORCH_STRONG_POWER: the mount a wall_torch sits on must be driven by a wire
     that is IN-LINE (straight) with the mount, else /setblock won't invert.
     Flag mounts whose only redstone neighbor approaches from a corner.

Reports counts + a few examples per class. Exit nonzero if any hard errors.
"""
from __future__ import annotations
import sys, json, os
from collections import defaultdict

SOLID = lambda s: s.startswith("minecraft:stone") or s == "minecraft:redstone_block" or "lamp" in s
IS_WIRE = lambda s: s == "minecraft:redstone_wire"
IS_TORCH = lambda s: "torch" in s
IS_REP = lambda s: s.startswith("minecraft:repeater")

DIRS = {"north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0)}


def facing_of(s):
    if "facing=" not in s:
        return None
    return s.split("facing=")[1].split(",")[0].split("]")[0]


def lint(path):
    d = json.load(open(path))
    B = {}
    for x, y, z, s in d["blocks"]:
        B[(x, y, z)] = s
    inj = set(tuple(p) for p in d["inputs"].values())

    floating, torch_nomount, rep_dangle, torch_corner = [], [], [], []

    for (x, y, z), s in B.items():
        if IS_WIRE(s):
            below = B.get((x, y - 1, z))
            if below is None or not SOLID(below):
                floating.append((x, y, z))
        elif IS_TORCH(s):
            f = facing_of(s)  # wall torch points AWAY from mount; mount is opposite
            if f and f in DIRS:
                dx, dy, dz = DIRS[f]
                mount = (x - dx, y - dy, z - dz)  # opposite of facing
                mb = B.get(mount)
                if mb is None or not SOLID(mb):
                    torch_nomount.append((x, y, z))
                else:
                    # strong-power check: mount must have a wire IN-LINE feeding it.
                    # in-line = the wire is on the far side of the mount from torch,
                    # i.e. at mount +(-dx,*,-dz) roughly, or directly powering mount.
                    # Practically: some wire neighbor of mount that is straight.
                    inline = B.get((mount[0] - dx, mount[1], mount[2] - dz))
                    src_ok = (inline is not None and (IS_WIRE(inline) or inline == "minecraft:redstone_block" or IS_REP(inline)))
                    # also accept a wire sitting ON TOP of the mount (standing feed)
                    top = B.get((mount[0], mount[1] + 1, mount[2]))
                    top_ok = top is not None and IS_WIRE(top)
                    if not (src_ok or top_ok):
                        torch_corner.append((x, y, z))
        elif IS_REP(s):
            f = facing_of(s)  # repeater OUTPUT points to facing; INPUT from opposite
            if f and f in DIRS:
                dx, dy, dz = DIRS[f]
                infrom = (x + dx, y, z + dz)   # input side (behind), opposite of output
                # NB repeater facing=west means output to west, input from east
                back = (x - dx, y, z - dz)
                inb = B.get(back)
                out = B.get((x + dx, y, z + dz))
                fed = (inb is not None and (IS_WIRE(inb) or inb == "minecraft:redstone_block" or IS_TORCH(inb) or IS_REP(inb))) or (x - dx, y, z - dz) in inj or back in inj
                used = (out is not None and (IS_WIRE(out) or IS_TORCH(out) or IS_REP(out) or SOLID(out)))
                if not fed or not used:
                    rep_dangle.append((x, y, z, f, "nofeed" if not fed else "noload"))

    def show(name, lst):
        print(f"  {name}: {len(lst)}")
        for e in lst[:6]:
            print(f"     {e}")

    print(f"=== lint {d['name']} ({len(B)} blocks) ===")
    show("FLOATING_DUST", floating)
    show("TORCH_NO_MOUNT", torch_nomount)
    show("TORCH_CORNER_FEED (won't invert)", torch_corner)
    show("REPEATER_DANGLE", rep_dangle)
    hard = len(floating) + len(torch_nomount)
    soft = len(torch_corner) + len(rep_dangle)
    print(f"  HARD errors (floating/no-mount): {hard}")
    print(f"  SOFT warnings (corner/dangle): {soft}")
    return hard, soft


if __name__ == "__main__":
    hard, soft = lint(sys.argv[1])
    sys.exit(1 if hard else 0)
