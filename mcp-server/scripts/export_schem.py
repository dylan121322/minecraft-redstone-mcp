#!/usr/bin/env python3
"""Export litematic/schematic blocks as JSON for builder scripts."""
import nucleation as nuc, json, sys, os

# Accept path as command line arg, fall back to relative path
if len(sys.argv) > 1:
    path = sys.argv[1]
else:
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'schematics', 'smol_DIKC-4_fibonacci.litematic')

schem = nuc.Schematic.open(path)
bounds_raw = schem.bounding_box_json()
bounds = json.loads(bounds_raw) if isinstance(bounds_raw, str) else list(bounds_raw)
print(f"Bounds: {bounds}", file=sys.stderr)

blocks = []
for x in range(bounds[0], bounds[3]+1):
    for y in range(bounds[1], bounds[4]+1):
        for z in range(bounds[2], bounds[5]+1):
            block = schem.get_block_string(x, y, z)
            if block and not block.startswith('minecraft:air') and block != 'minecraft:cave_air' and block != 'minecraft:void_air':
                blocks.append([x, y, z, block])

print(json.dumps({'bounds': bounds, 'blocks': blocks}))
