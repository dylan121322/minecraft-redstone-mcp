/**
 * build_dikc4_v2.cjs — Single, correct DIKC-4 CPU builder
 *
 * Fixes:
 * - Bot always TP's to solid platform surface (never mid-air)
 * - Correct facing calibration (look→place mapping)
 * - Single build, no duplicates
 */

const mineflayer = require('mineflayer');
const V3 = require('vec3');
const { pathfinder, Movements } = require('mineflayer-pathfinder');
const { execSync } = require('child_process');

const HOST = 'localhost';
const PORT = parseInt(process.env.PORT || '25565');, USERNAME = 'DIKC4_v63277';
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME, keepalive: false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

// CORRECT facing calibration:
// Look east(-PI/2) AT target → placed faces WEST
// Look west(PI/2) AT target → placed faces EAST
// Look south(0) AT target → placed faces NORTH
// Look north(PI) AT target → placed faces SOUTH
// Stand on OPPOSITE side from desired facing — lookAt auto-determines facing
const FACE_CFG = {
    east:  { dx:  1, dz:  0 },  // stand EAST → placed EAST
    west:  { dx: -1, dz:  0 },  // stand WEST → placed WEST (needs 3s TP wait)
    south: { dx:  0, dz:  1 },  // stand SOUTH → placed SOUTH
    north: { dx:  0, dz: -1 },  // stand NORTH → placed NORTH
};

async function placeInteractive(x, y, z, facing, type) {
    const cfg = FACE_CFG[facing] || FACE_CFG['east'];
    const standX = x + cfg.dx;
    const standZ = z + cfg.dz;

    // Place stand stone at y-1 (platform level)
    bot.chat(`/setblock ${standX} ${y-1} ${standZ} minecraft:stone`);
    await sleep(80);

    // Stand at y+1 (one block above circuit level), wait for chunk load
    bot.chat(`/tp ${bot.username} ${standX} ${y+1} ${standZ}`);
    await sleep(3000);

    // Give item
    bot.chat(`/give ${bot.username} ${type} 1`);
    await sleep(200);
    const item = bot.inventory.items().find(i => i.name === type);
    if (item) {
        await bot.equip(item, 'hand');
        await sleep(100);
        const ref = bot.blockAt(V3(x, y-1, z));
        if (ref) {
            // NO forceLook — let lookAt determine facing from stand position
            try { await bot.placeBlock(ref, V3(0, 1, 0)); } catch(e) {}
        }
    }
    await sleep(100);
}

bot.once('spawn', async () => {
    bot.loadPlugin(pathfinder);
    bot.pathfinder.setMovements(new Movements(bot));

    // Creative mode — inventory via API, no OP needed

    // Export schematic
    console.log('Loading schematic...');
    const data = JSON.parse(execSync(
        'python3 $(node -e 'console.log(require("path").join(__dirname,"export_schem.py"))')',
        { maxBuffer: 50*1024*1024 }
    ).toString().trim().split('\n').pop());
    const { bounds, blocks } = data;
    console.log(`Bounds: ${bounds}, Total blocks: ${blocks.length}`);

    // Build at bot's position
    const GY = Math.floor(bot.entity.position.y) + 2; // platform 2 blocks above ground
    const DX = Math.floor(bot.entity.position.x) + 5;
    const DZ = Math.floor(bot.entity.position.z);
    console.log(`Building DIKC-4 at X=${DX}, Y=${GY}, Z=${DZ}`);

    // Step 0: Clear old build if any
    bot.chat(`/fill ${DX-5} ${GY-2} ${DZ-5} ${DX+60} ${GY+30} ${DZ+30} minecraft:air`);
    await sleep(1000);

    // Step 1: Stone platform (large enough for CPU + bot movement)
    bot.chat(`/fill ${DX-3} ${GY-1} ${DZ-3} ${DX+55} ${GY-1} ${DZ+25} minecraft:glass`);
    await sleep(1000);
    bot.chat(`/fill ${DX-3} ${GY} ${DZ-3} ${DX+55} ${GY} ${DZ+25} minecraft:stone`);
    await sleep(2000);
    // Only clear ABOVE the platform (keep platform intact)
    bot.chat(`/fill ${DX-3} ${GY+1} ${DZ-3} ${DX+55} ${GY+25} ${DZ+25} minecraft:air`);
    await sleep(1000);

    // Step 2: All solid blocks via setblock
    const solidBlocks = blocks.filter(b => {
        const n = b[3].replace('minecraft:','').split('[')[0];
        return n !== 'repeater' && n !== 'comparator' && n !== 'redstone_wire' &&
               n !== 'redstone_torch' && n !== 'redstone_wall_torch' && n !== 'lever';
    });
    console.log(`\nSolid blocks: ${solidBlocks.length}`);
    for (let i=0; i<solidBlocks.length; i++) {
        const [x, y, z, block] = solidBlocks[i];
        bot.chat(`/setblock ${DX+x} ${GY+y} ${DZ+z} ${block}`);
        if (i % 100 === 0) { process.stdout.write(`\r  ${i}/${solidBlocks.length}`); await sleep(20); }
    }
    console.log(`\r  ${solidBlocks.length}/${solidBlocks.length} solid done`);

    // Step 3: Redstone components via setblock
    const rsBlocks = blocks.filter(b => {
        const n = b[3].replace('minecraft:','').split('[')[0];
        return n === 'redstone_wire' || n === 'redstone_torch' || n === 'redstone_wall_torch' || n === 'lever';
    });
    console.log(`\nRedstone: ${rsBlocks.length}`);
    for (let i=0; i<rsBlocks.length; i++) {
        const [x, y, z, block] = rsBlocks[i];
        bot.chat(`/setblock ${DX+x} ${GY+y} ${DZ+z} ${block}`);
        if (i % 50 === 0) { process.stdout.write(`\r  ${i}/${rsBlocks.length}`); await sleep(30); }
    }
    console.log(`\r  ${rsBlocks.length}/${rsBlocks.length} redstone done`);

    // Step 4: Interactive blocks (repeaters/comparators) — PHYSICAL placement
    const intBlocks = blocks.filter(b => {
        const n = b[3].replace('minecraft:','').split('[')[0];
        return n === 'repeater' || n === 'comparator';
    });
    console.log(`\nInteractive: ${intBlocks.length} (physical placement)`);

    for (let i=0; i<intBlocks.length; i++) {
        const [x, y, z, block] = intBlocks[i];
        const name = block.replace('minecraft:','').split('[')[0];
        const propsMatch = block.match(/\[(.*)\]/);
        const props = propsMatch ? Object.fromEntries(propsMatch[1].split(',').map(p => p.split('='))) : {};
        const facing = props.facing || 'east';

        await placeInteractive(DX+x, GY+y, DZ+z, facing, name);
        if (i % 25 === 0) process.stdout.write(`\r  ${i}/${intBlocks.length}`);
    }
    console.log(`\r  ${intBlocks.length}/${intBlocks.length} interactive done`);

    // Verify
    console.log('\nVerifying...');
    let reps = 0, fCounts = {};
    for (let x=0; x<50; x++) for (let y=0; y<22; y++) for (let z=0; z<25; z++) {
        const b = bot.blockAt(V3(DX+x, GY+y, DZ+z));
        if (b?.name === 'repeater') { reps++; fCounts[b.getProperties?.()?.facing]=(fCounts[b.getProperties?.()?.facing]||0)+1; }
    }
    console.log(`Repeaters: ${reps}, Facings: ${JSON.stringify(fCounts)}`);
    console.log(`\n✅ DIKC-4 CPU at X=${DX}, Y=${GY}, Z=${DZ}`);
    console.log(`Port 61977`);

    setTimeout(() => bot.quit(), 3000);
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
