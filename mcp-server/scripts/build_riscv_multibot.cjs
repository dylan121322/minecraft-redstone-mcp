/**
 * build_riscv_multibot.cjs — RISC-V Tiny ALU, multi-bot cooperative builder
 *
 * KEY INSIGHT (measured): server drops commands sent faster than ~150ms/cmd
 * PER PLAYER. N bots each rate-limited to 200ms → N× throughput, no drops.
 *
 * Strategy:
 *   - Partition the 8-bit RCA by bit: bot k owns a contiguous set of bits.
 *   - Bits are spatially disjoint (bit i at x=BX+i*15) → zero write conflict.
 *   - Coordinator places glass base, then all bots build in parallel.
 *   - Each bot: stones+wires (Y) enqueued before torches (Y+1) → correct order.
 *   - Coordinator verifies at the end.
 *
 * Usage: PORT=56412 NBOTS=4 node build_riscv_multibot.cjs
 */
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const PORT = parseInt(process.env.PORT || '56412');
const HOST = process.env.HOST || 'localhost';
const NBOTS = parseInt(process.env.NBOTS || '4');
const CMD_GAP = 200;         // ms per command, per bot (measured safe > 150ms)
const SP = 15;               // x-spacing per full-adder bit

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ============================================================
// Command generators — pure functions returning ordered arrays.
// Order within array MATTERS: stones/wires (Y) first, torches (Y+1) last.
// ============================================================
function xorGate(x, y, z) {
    return [
        `/setblock ${x+1} ${y} ${z}   minecraft:stone`,
        `/setblock ${x+1} ${y} ${z+2} minecraft:stone`,
        `/setblock ${x+2} ${y} ${z+1} minecraft:stone`,
        `/setblock ${x+3} ${y} ${z+1} minecraft:stone`,
        `/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`,
        `/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x+2} ${y} ${z}   minecraft:redstone_wire`,
        `/setblock ${x+2} ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x+4} ${y} ${z+1} minecraft:redstone_wire`,
        `/setblock ${x+1} ${y+1} ${z}   minecraft:redstone_torch[lit=true]`,
        `/setblock ${x+1} ${y+1} ${z+2} minecraft:redstone_torch[lit=true]`,
        `/setblock ${x+2} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`,
        `/setblock ${x+3} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`,
    ];
}
function andGate(x, y, z) {
    return [
        `/setblock ${x+1} ${y} ${z}   minecraft:stone`,
        `/setblock ${x+1} ${y} ${z+2} minecraft:stone`,
        `/setblock ${x+3} ${y} ${z+1} minecraft:stone`,
        `/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`,
        `/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x+2} ${y} ${z}   minecraft:redstone_wire`,
        `/setblock ${x+2} ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x+2} ${y} ${z+1} minecraft:redstone_wire`,
        `/setblock ${x+4} ${y} ${z+1} minecraft:redstone_wire`,
        `/setblock ${x+1} ${y+1} ${z}   minecraft:redstone_torch[lit=true]`,
        `/setblock ${x+1} ${y+1} ${z+2} minecraft:redstone_torch[lit=true]`,
        `/setblock ${x+3} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`,
    ];
}
function orGate(x, y, z) {
    return [
        `/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`,
        `/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x}   ${y} ${z+1} minecraft:redstone_wire`,
        `/setblock ${x+1} ${y} ${z+1} minecraft:redstone_wire`,
    ];
}
function fullAdder1b(x, y, z) {
    return [
        ...xorGate(x, y, z),
        ...xorGate(x+5, y, z+2),
        ...andGate(x+3, y, z+3),
        ...andGate(x+5, y, z+5),
        ...orGate(x+9, y, z+4),
        `/setblock ${x+4} ${y} ${z+2} minecraft:redstone_wire`,
        `/setblock ${x+4} ${y} ${z+3} minecraft:redstone_wire`,
        `/setblock ${x+4} ${y} ${z+4} minecraft:redstone_wire`,
        `/setblock ${x+4} ${y} ${z+5} minecraft:redstone_wire`,
        `/setblock ${x}   ${y} ${z+3} minecraft:redstone_wire`,
        `/setblock ${x+8} ${y} ${z+4} minecraft:redstone_wire`,
        `/setblock ${x+9} ${y} ${z+5} minecraft:redstone_wire`,
        `/setblock ${x+9} ${y} ${z+4} minecraft:redstone_wire`,
    ];
}

// Build the per-bit command list for the whole ALU.
// Returns { bitCmds: [[...], ...], glassFill, verifyPoints }
function generateALU(BX, BY, BZ) {
    const bitCmds = [];
    for (let i = 0; i < 8; i++) {
        const fx = BX + i * SP;
        const cmds = fullAdder1b(fx, BY, BZ);
        // carry chain wire to next bit
        if (i < 7) {
            const coutX = fx + 11;
            for (let wx = coutX; wx < fx + SP; wx++)
                cmds.push(`/setblock ${wx} ${BY} ${BZ+3} minecraft:redstone_wire`);
        }
        // output lamp + wire for this bit's sum
        const sx = fx + 9;
        cmds.push(`/setblock ${sx-1} ${BY} ${BZ+1} minecraft:redstone_wire`);
        cmds.push(`/setblock ${sx}   ${BY} ${BZ+1} minecraft:redstone_lamp`);
        // input levers A/B for this bit
        cmds.push(`/setblock ${fx-2} ${BY} ${BZ}   minecraft:lever[facing=east,powered=false]`);
        cmds.push(`/setblock ${fx-2} ${BY} ${BZ+2} minecraft:lever[facing=east,powered=false]`);
        bitCmds.push(cmds);
    }
    return bitCmds;
}

// ============================================================
// Bot factory
// ============================================================
function makeBot(name) {
    return new Promise((resolve) => {
        const b = mineflayer.createBot({ host: HOST, port: PORT, username: name, keepalive: false });
        b.once('spawn', () => resolve(b));
        b.on('error', e => { if (!e.message?.includes('ECONNRESET')) console.error(`[${name}] ${e.message}`); });
        b.on('kicked', r => console.error(`[${name}] kicked: ${r}`));
    });
}

// Extract the target (x,y,z) from a /setblock or /fill command.
function cmdCoord(c) {
    const m = c.match(/-?\d+/g);
    return m ? { x: +m[0], y: +m[1], z: +m[2] } : null;
}

// Teleport bot near a coordinate so the chunk stays loaded during placement.
// MEASURED: /setblock silently fails beyond ~13 chunks (~210 blocks) from bot.
async function botTP(bot, x, y, z) {
    bot.chat(`/tp ${bot.username} ${x} ${y + 2} ${z}`);
    await sleep(600); // allow chunk load
}

// Dispatch a command list on one bot with strict rate limit.
// Re-teleports whenever the next target drifts too far (keeps chunk loaded).
async function botDrain(bot, name, cmds, onProgress) {
    let n = 0;
    let anchor = null;
    const MAX_DRIFT = 120; // stay well inside the ~210-block load radius
    for (const c of cmds) {
        const co = cmdCoord(c);
        if (co) {
            if (!anchor ||
                Math.abs(co.x - anchor.x) > MAX_DRIFT ||
                Math.abs(co.z - anchor.z) > MAX_DRIFT) {
                await botTP(bot, co.x, co.y, co.z);
                anchor = co;
            }
        }
        bot.chat(c);
        n++;
        if (onProgress && n % 10 === 0) onProgress(name, n, cmds.length);
        await sleep(CMD_GAP);
    }
    return n;
}

// ============================================================
// Main
// ============================================================
(async () => {
    console.log(`=== RISC-V Tiny ALU — Multi-bot (${NBOTS} bots) ===`);
    const start = Date.now();

    // Spawn coordinator first to get position + place glass
    const coord = await makeBot('RV_coord');
    const p = coord.entity.position;
    const BX = Math.round(p.x) + 5, BY = Math.round(p.y), BZ = Math.round(p.z);
    console.log(`Origin: (${BX}, ${BY}, ${BZ})`);

    // Glass base: fill in segments, teleporting coordinator to each so
    // the target chunks are loaded (a single 125-wide fill spans >7 chunks
    // but the /fill command itself works region-by-region only if loaded).
    console.log('Glass base (segmented)...');
    const spanX = 8 * SP + 5;
    for (let sx = -3; sx < spanX; sx += 100) {
        const segEnd = Math.min(sx + 99, spanX);
        coord.chat(`/tp RV_coord ${BX + sx + 50} ${BY + 2} ${BZ + 8}`);
        await sleep(600);
        coord.chat(`/fill ${BX + sx} ${BY-1} ${BZ-3} ${BX + segEnd} ${BY-1} ${BZ+20} minecraft:glass`);
        await sleep(1200);
    }
    await sleep(1500);

    // Generate work, partition by bit (contiguous blocks per bot)
    const bitCmds = generateALU(BX, BY, BZ);
    const totalCmds = bitCmds.reduce((s, c) => s + c.length, 0);
    console.log(`Total: ${totalCmds} commands across 8 bits`);

    // Spawn worker bots (coordinator is worker 0)
    const workers = [coord];
    for (let k = 1; k < NBOTS; k++) {
        workers.push(await makeBot(`RV_w${k}`));
        await sleep(500); // stagger joins
    }
    console.log(`${workers.length} bots ready.`);

    // Partition CONTIGUOUSLY: each bot owns adjacent bits (minimizes teleports,
    // keeps each bot inside one loaded region).
    const partitions = workers.map(() => []);
    const bitsPerBot = Math.ceil(8 / workers.length);
    for (let bit = 0; bit < 8; bit++) {
        const owner = Math.min(Math.floor(bit / bitsPerBot), workers.length - 1);
        partitions[owner].push(...bitCmds[bit]);
    }
    partitions.forEach((pt, k) => console.log(`  bot${k} (${workers[k].username}): ${pt.length} cmds`));

    // Progress tracker
    const progress = {};
    const onProg = (name, n, tot) => { progress[name] = `${n}/${tot}`; };
    const reporter = setInterval(() => {
        const parts = Object.entries(progress).map(([k, v]) => `${k}:${v}`).join('  ');
        process.stdout.write(`\r  ${parts} — ${((Date.now()-start)/1000).toFixed(0)}s   `);
    }, 1500);

    // Dispatch all bots in PARALLEL
    const results = await Promise.all(
        workers.map((b, k) => botDrain(b, b.username, partitions[k], onProg))
    );
    clearInterval(reporter);
    const dispatched = results.reduce((s, n) => s + n, 0);
    console.log(`\n  All bots done. ${dispatched} cmds in ${((Date.now()-start)/1000).toFixed(1)}s`);
    console.log(`  Effective rate: ${(dispatched / ((Date.now()-start)/1000)).toFixed(1)} cmds/s (${NBOTS}x single-bot)`);

    // Settle
    await sleep(5000);

    // ============================================================
    // Verify (coordinator)
    // ============================================================
    console.log('\n=== Verification ===');
    let ok = 0, total = 0;
    const missing = [];
    for (let i = 0; i < 8; i++) {
        const fx = BX + i * SP;
        // move coordinator near this bit so the chunk is loaded for reading
        coord.chat(`/tp RV_coord ${fx + 4} ${BY + 2} ${BZ + 2}`);
        await sleep(500);
        const checks = [
            [fx+1, BY,   BZ,   'stone',         `b${i}_mountA`],
            [fx+1, BY+1, BZ,   'redstone_torch',`b${i}_torchA`],
            [fx,   BY,   BZ,   'redstone_wire', `b${i}_Ain`],
            [fx,   BY,   BZ+2, 'redstone_wire', `b${i}_Bin`],
            [fx+1, BY,   BZ+2, 'stone',         `b${i}_mountB`],
            [fx+1, BY+1, BZ+2, 'redstone_torch',`b${i}_torchB`],
            [fx+4, BY,   BZ+1, 'redstone_wire', `b${i}_xor1out`],
            [fx+9, BY,   BZ+1, 'redstone_lamp', `b${i}_lamp`],
            [fx-2, BY,   BZ,   'lever',         `b${i}_leverA`],
            [fx-2, BY,   BZ+2, 'lever',         `b${i}_leverB`],
        ];
        for (const [x, y, z, exp, label] of checks) {
            total++;
            const blk = coord.blockAt(new Vec3(x, y, z));
            if (blk && blk.name === exp) ok++;
            else missing.push(`${label}@(${x},${y},${z})=${blk ? blk.name : 'NULL'}`);
        }
    }
    const pct = (ok / total * 100).toFixed(0);
    console.log(`Blocks correct: ${ok}/${total} (${pct}%)`);
    if (missing.length && missing.length <= 20) console.log('  Missing: ' + missing.join('  '));
    else if (missing.length) console.log(`  ${missing.length} missing (first 10): ` + missing.slice(0,10).join('  '));

    if (ok / total >= 0.95) {
        console.log('\n✅ BUILD SUCCESSFUL — 8-bit ALU intact!');
        console.log(`   Multi-bot beat rate limit: ${NBOTS} bots × ~5 cmds/s = ~${NBOTS*5} cmds/s`);
        console.log('\n   Test: flip A/B levers (west side), read SUM lamps (east side).');
    } else if (ok / total >= 0.7) {
        console.log('\n⚠️  PARTIAL — some blocks missing (check partition boundaries)');
    } else {
        console.log('\n❌ FAILED');
    }

    // Disconnect all
    for (const b of workers) b.quit();
    setTimeout(() => process.exit(0), 2000);
})().catch(e => { console.error('FATAL', e); process.exit(1); });

setTimeout(() => { console.log('Timeout'); process.exit(1); }, 300000);
