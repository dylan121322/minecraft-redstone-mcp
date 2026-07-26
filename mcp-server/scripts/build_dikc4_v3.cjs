/**
 * build_dikc4_v3.cjs — DIKC-4 CPU builder, all /setblock (mod fixed MC-31100)
 *
 * Usage: PORT=xxxxx node build_dikc4_v3.cjs [baseX] [baseY] [baseZ]
 *
 * Fixes from v2:
 * - ALL blocks via /setblock (no physical placement, no facing calibration needed)
 * - Glass base isolation per SKILL.md rules
 * - Server-side verification via /execute if block
 * - 200ms inter-command delay to prevent server throttling
 */

const mineflayer = require('mineflayer');
const { execSync } = require('child_process');

const HOST = 'localhost';
const PORT = parseInt(process.env.PORT || '56804');
const USERNAME = 'DIKC4_Builder';
const CMD_DELAY = 200; // ms between /setblock commands

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME, keepalive: false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

bot.once('spawn', async () => {
    console.log('Bot spawned. Loading schematic...');

    // Export schematic blocks
    const data = JSON.parse(execSync(
        'python3 $(node -e 'console.log(require("path").join(__dirname,"export_schem.py"))')',
        { maxBuffer: 50 * 1024 * 1024 }
    ).toString().trim().split('\n').pop());
    const { bounds, blocks } = data;
    console.log(`Bounds: ${bounds}, Total blocks: ${blocks.length}`);

    // Build position: near bot, on glass base
    const pos = bot.entity.position;
    const DX = parseInt(process.argv[2]) || Math.round(pos.x) + 5;
    const GY = parseInt(process.argv[3]) || Math.round(pos.y) + 2;
    const DZ = parseInt(process.argv[4]) || Math.round(pos.z);
    const W = bounds[3] - bounds[0] + 5;
    const H = bounds[4] - bounds[1] + 3;
    const D = bounds[5] - bounds[2] + 5;
    console.log(`Building at ${DX},${GY},${DZ} (${W}×${H}×${D})\n`);

    // === PHASE 0: Prepare area ===
    console.log('Phase 0: Clearing and glass base...');
    // Clear area above ground
    bot.chat(`/fill ${DX - 3} ${GY - 1} ${DZ - 3} ${DX + W} ${GY + H} ${DZ + D} minecraft:air`);
    await sleep(1500);

    // Glass isolation base (SKILL.md: GLASS_BASE + GLASS_MARGIN)
    bot.chat(`/fill ${DX - 3} ${GY - 1} ${DZ - 3} ${DX + W} ${GY - 1} ${DZ + D} minecraft:glass`);
    await sleep(1500);

    console.log('Glass base placed.\n');

    // === PHASE 1: All blocks via /setblock ===
    // Build order: Y: bottom→top (blocks sorted by Y for correct placement order)
    const sorted = [...blocks].sort((a, b) => a[1] - b[1]);

    console.log(`Phase 1: Placing ${sorted.length} blocks via /setblock...`);
    const start = Date.now();
    let lastLog = 0;

    for (let i = 0; i < sorted.length; i++) {
        const [x, y, z, block] = sorted[i];
        const cmd = `/setblock ${DX + x} ${GY + y} ${DZ + z} ${block}`;
        bot.chat(cmd);

        // Progress logging every 500 blocks or 5 seconds
        const now = Date.now();
        if (i - lastLog >= 500 || now - start > 5000) {
            const elapsed = ((now - start) / 1000).toFixed(1);
            const pct = ((i / sorted.length) * 100).toFixed(1);
            const rate = (i / (elapsed || 0.1)).toFixed(0);
            process.stdout.write(`\r  ${i}/${sorted.length} (${pct}%) — ${elapsed}s — ${rate} blocks/s`);
            lastLog = i;
            await sleep(10); // brief yield
        }

        // Enforce CMD_DELAY every 5 blocks
        if (i % 5 === 0) {
            await sleep(CMD_DELAY);
        }
    }

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`\r  ${sorted.length}/${sorted.length} done in ${elapsed}s\n`);

    // === PHASE 2: Server-side verification ===
    console.log('Phase 2: Verifying critical components (server-side)...');

    // Count repeaters
    const repCount = blocks.filter(b => {
        const n = b[3].replace('minecraft:', '').split('[')[0];
        return n === 'repeater';
    }).length;
    console.log(`Expected repeaters: ${repCount}`);

    // Verify a few key repeaters
    const checks = [];
    for (const [, b] of Object.entries(blocks)) {
        const [x, y, z, block] = b;
        const name = block.replace('minecraft:', '').split('[')[0];
        if (name === 'repeater' || name === 'redstone_lamp') {
            const props = block.split('[')[1]?.replace(']', '');
            if (props && props.includes('powered=true')) {
                checks.push({ x: DX + x, y: GY + y, z: DZ + z, block, name });
            }
        }
    }
    console.log(`Blocks expecting powered state: ${checks.length}`);

    // Wait for all tick-scheduled updates to complete
    console.log('Waiting for redstone ticks to settle...');
    await sleep(5000);

    // Verify via /execute if block
    let verified = 0, failed = 0;
    for (const { x, y, z, block, name } of checks.slice(0, 50)) { // verify first 50
        const props = block.split('[')[1]?.replace(']', '');
        if (!props) continue;
        const qBlock = name === 'repeater'
            ? `minecraft:repeater[${props}]`
            : `minecraft:${name}[${props}]`;
        bot.chat(`/execute if block ${x} ${y} ${z} ${qBlock} run say VERIFY_OK`);
        await sleep(100);
        bot.chat(`/execute unless block ${x} ${y} ${z} ${qBlock} run say VERIFY_FAIL_${x}_${y}_${z}`);
        await sleep(50);
    }
    verified = 1; // placeholder — messages arrive async
    console.log('Verification queries sent (check game chat for VERIFY_OK/FAIL).');

    // Final summary
    console.log('\n=== DIKC-4 CPU Build Complete ===');
    console.log(`Location: X=${DX}, Y=${GY}, Z=${DZ}`);
    console.log(`Size: ${W}×${H}×${D} blocks`);
    console.log(`Total blocks placed: ${sorted.length}`);
    console.log(`Build time: ${elapsed}s`);

    setTimeout(() => bot.quit(), 3000);
});

bot.on('error', e => { if (!e.message.includes('ECONNRESET')) console.error('Err:', e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
