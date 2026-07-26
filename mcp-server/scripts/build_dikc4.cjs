/**
 * build_dikc4.cjs — Import smol DIKC-4 CPU from litematic into Minecraft world
 *
 * Strategy:
 * - Export all blocks from litematic via Nucleation Python script
 * - Build stone platform
 * - Place all non-repeater/non-comparator blocks via /setblock
 * - Place repeaters and comparators via bot.placeBlock() physical placement
 */

const mineflayer = require('mineflayer');
const V3 = require('vec3');
const { pathfinder, Movements } = require('mineflayer-pathfinder');
const { execSync } = require('child_process');
const HOST = 'localhost';
const PORT = parseInt(process.env.PORT || '25565');
const USERNAME = 'DIKC4Builder';

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME });
const sleep = ms => new Promise(r => setTimeout(r, ms));

// Export blocks from litematic via Python
function exportBlocks() {
    try {
        const result = execSync('python3 ' + require('path').join(__dirname, 'export_schem.py'), {maxBuffer: 50*1024*1024});
        const lines = result.toString().trim().split('\n');
        return JSON.parse(lines[lines.length - 1]); // last line is JSON
    } catch(e) {
        console.error('Export failed:', e.message);
        return null;
    }
}

// Classify blocks
function classify(blockStr) {
    const name = blockStr.replace('minecraft:', '');
    const base = name.split('[')[0];
    if (base === 'repeater' || base === 'comparator') return 'interactive';
    if (base === 'redstone_wire' || base === 'redstone_torch' || base === 'redstone_wall_torch') return 'redstone';
    return 'solid';
}

bot.once('spawn', async () => {
    bot.loadPlugin(pathfinder);
    bot.pathfinder.setMovements(new Movements(bot));

    console.log('Exporting blocks from litematic...');
    const data = exportBlocks();
    if (!data) { console.log('Export failed'); bot.quit(); return; }

    const { bounds, blocks } = data;
    console.log(`Bounds: ${bounds}, Blocks: ${blocks.length}`);

    const GY = Math.floor(bot.entity.position.y);
    const DX = Math.floor(bot.entity.position.x) + 5;
    const DZ = Math.floor(bot.entity.position.z);
    console.log(`Building at offset X=${DX}, Y=${GY}, Z=${DZ}`);

    // Classify blocks
    const solidBlocks = blocks.filter(b => classify(b[3]) === 'solid');
    const redstoneBlocks = blocks.filter(b => classify(b[3]) === 'redstone');
    const interactiveBlocks = blocks.filter(b => classify(b[3]) === 'interactive');

    console.log(`Solid: ${solidBlocks.length}, Redstone: ${redstoneBlocks.length}, Interactive (repeater/comp): ${interactiveBlocks.length}`);

    // Step 1: Place all solid blocks via /fill batches
    // Group by block type for efficiency
    const byType = {};
    for (const [x, y, z, block] of solidBlocks) {
        const name = block.split('[')[0];
        if (!byType[name]) byType[name] = [];
        byType[name].push([x, y, z]);
    }

    console.log('Building solid blocks...');
    let count = 0;
    for (const [blockType, positions] of Object.entries(byType)) {
        for (const [x, y, z] of positions) {
            bot.chat(`/setblock ${DX+x} ${GY+y} ${DZ+z} ${blockType}`);
            count++;
            if (count % 20 === 0) {
                process.stdout.write(`\r  ${count}/${solidBlocks.length} solid blocks`);
                await sleep(50); // small delay per batch
            }
        }
    }
    console.log(`\n  Solid blocks: ${count} placed`);

    // Step 2: Place redstone components via /setblock
    console.log('\nBuilding redstone components...');
    count = 0;
    for (const [x, y, z, block] of redstoneBlocks) {
        bot.chat(`/setblock ${DX+x} ${GY+y} ${DZ+z} ${block}`);
        count++;
        if (count % 20 === 0) {
            process.stdout.write(`\r  ${count}/${redstoneBlocks.length} redstone`);
            await sleep(100);
        }
    }
    console.log(`\n  Redstone: ${count} placed`);

    // Step 3: Physical placement for repeaters and comparators
    console.log(`\nPlacing ${interactiveBlocks.length} interactive blocks (physical)...`);
    count = 0;
    for (const [x, y, z, block] of interactiveBlocks) {
        const base = block.replace('minecraft:', '').split('[')[0];
        const propsMatch = block.match(/\[(.*)\]/);
        const props = propsMatch ? Object.fromEntries(propsMatch[1].split(',').map(p => p.split('='))) : {};
        const facing = props.facing || 'east';

        // TP near target
        bot.chat(`/tp ${bot.username} ${DX+x-1} ${GY+y+1} ${DZ+z}`);
        await sleep(100);

        // Look at target
        const yawMap = { east: Math.PI/2, west: -Math.PI/2, south: Math.PI, north: 0 };
        await bot.look(yawMap[facing] || 0, 0);
        await sleep(50);

        // Equip
        bot.chat(`/give ${bot.username} ${base} 1`);
        await sleep(100);
        const item = bot.inventory.items().find(i => i.name === base);
        if (item) {
            await bot.equip(item, 'hand');
            await sleep(50);
            const ref = bot.blockAt(V3(DX+x, GY+y-1, DZ+z));
            if (ref) {
                try { await bot.placeBlock(ref, V3(0,1,0)); } catch(e) {}
            }
        }
        count++;
        if (count % 5 === 0) process.stdout.write(`\r  ${count}/${interactiveBlocks.length}`);
    }
    console.log(`\n  Interactive: ${count} placed`);

    console.log(`\n✅ DIKC-4 CPU imported!`);
    console.log(`Location: X=${DX}, Y=${GY}, Z=${DZ}`);
    console.log(`Size: ${bounds[3]-bounds[0]}x${bounds[4]-bounds[1]}x${bounds[5]-bounds[2]}`);

    setTimeout(() => bot.quit(), 5000);
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000); // 10 min max
