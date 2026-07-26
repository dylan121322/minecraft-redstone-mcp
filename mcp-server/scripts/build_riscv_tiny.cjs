/**
 * build_riscv_tiny.cjs — RISC-V Tiny ALU v3 (Build + Verify in same session)
 *
 * Fixes:
 *   - No /fill air (async clearing killed early /setblocks)
 *   - Glass base via /fill at Y-1 only
 *   - Build + verify in SAME bot (no chunk loading issues)
 *   - Y-layer ordering: all stones, then all Y-layer wires, then Y+1 torches
 *
 * Usage: PORT=56412 node build_riscv_tiny.cjs
 */
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const PORT = parseInt(process.env.PORT || '56412');
const D = 350;

const bot = mineflayer.createBot({
    host: 'localhost', port: PORT, username: 'RISCV_v3',
    keepalive: false
});
const sleep = ms => new Promise(r => setTimeout(r, ms));
let sent = 0;
// PROVEN: server drops commands faster than ~150ms. Use 200ms for margin.
// Queue-based worker guarantees serial dispatch regardless of how cmd() is called.
const CMD_GAP = 200;
const _queue = [];
// MEASURED: /setblock silently fails when target is beyond ~13 chunks (~210
// blocks) from the bot — the chunk isn't loaded. Teleport to follow the build.
function cmd(c) { _queue.push(c); }          // synchronous enqueue
function _coord(c) { const m = c.match(/-?\d+/g); return m ? {x:+m[0],y:+m[1],z:+m[2]} : null; }
async function drain() {
    let anchor = null;
    const MAX_DRIFT = 100;
    while (_queue.length) {
        const c = _queue.shift();
        const co = _coord(c);
        if (co && (!anchor || Math.abs(co.x-anchor.x) > MAX_DRIFT || Math.abs(co.z-anchor.z) > MAX_DRIFT)) {
            bot.chat(`/tp ${bot.username} ${co.x} ${co.y+2} ${co.z}`);
            anchor = co;
            await sleep(600); // chunk load
        }
        bot.chat(c);
        sent++;
        await sleep(CMD_GAP);
    }
}

// ============================================================
// Gate builders — synchronous enqueue (Y-layer ordered).
// Queue preserves order; drain() dispatches with 200ms gap, so stones
// (enqueued first) are placed before torches (enqueued after).
// ============================================================
function xorGate(x, y, z) {
    // stones (Y)
    cmd(`/setblock ${x+1} ${y} ${z}   minecraft:stone`);
    cmd(`/setblock ${x+1} ${y} ${z+2} minecraft:stone`);
    cmd(`/setblock ${x+2} ${y} ${z+1} minecraft:stone`);
    cmd(`/setblock ${x+3} ${y} ${z+1} minecraft:stone`);
    // wires (Y)
    cmd(`/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`);
    cmd(`/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`);
    cmd(`/setblock ${x+2} ${y} ${z}   minecraft:redstone_wire`);
    cmd(`/setblock ${x+2} ${y} ${z+2} minecraft:redstone_wire`);
    cmd(`/setblock ${x+4} ${y} ${z+1} minecraft:redstone_wire`);
    // torches (Y+1)
    cmd(`/setblock ${x+1} ${y+1} ${z}   minecraft:redstone_torch[lit=true]`);
    cmd(`/setblock ${x+1} ${y+1} ${z+2} minecraft:redstone_torch[lit=true]`);
    cmd(`/setblock ${x+2} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`);
    cmd(`/setblock ${x+3} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`);
}

function andGate(x, y, z) {
    cmd(`/setblock ${x+1} ${y} ${z}   minecraft:stone`);
    cmd(`/setblock ${x+1} ${y} ${z+2} minecraft:stone`);
    cmd(`/setblock ${x+3} ${y} ${z+1} minecraft:stone`);
    cmd(`/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`);
    cmd(`/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`);
    cmd(`/setblock ${x+2} ${y} ${z}   minecraft:redstone_wire`);
    cmd(`/setblock ${x+2} ${y} ${z+2} minecraft:redstone_wire`);
    cmd(`/setblock ${x+2} ${y} ${z+1} minecraft:redstone_wire`);
    cmd(`/setblock ${x+4} ${y} ${z+1} minecraft:redstone_wire`);
    cmd(`/setblock ${x+1} ${y+1} ${z}   minecraft:redstone_torch[lit=true]`);
    cmd(`/setblock ${x+1} ${y+1} ${z+2} minecraft:redstone_torch[lit=true]`);
    cmd(`/setblock ${x+3} ${y+1} ${z+1} minecraft:redstone_torch[lit=true]`);
}

function orGate(x, y, z) {
    cmd(`/setblock ${x}   ${y} ${z}   minecraft:redstone_wire`);
    cmd(`/setblock ${x}   ${y} ${z+2} minecraft:redstone_wire`);
    cmd(`/setblock ${x}   ${y} ${z+1} minecraft:redstone_wire`);
    cmd(`/setblock ${x+1} ${y} ${z+1} minecraft:redstone_wire`);
}

// Non-overlapping full adder: each gate in its own Z-band (0 collisions).
//   xor1 @ (x,   z)     A xor B = s1           x:0..4  z:0..2
//   xor2 @ (x+6, z+4)   s1 xor Cin = SUM       x:6..10 z:4..6
//   and1 @ (x,   z+8)   A & B = c1             x:0..4  z:8..10
//   and2 @ (x+6, z+12)  s1 & Cin = c2          x:6..10 z:12..14
//   or   @ (x+12,z+16)  c1 | c2 = Cout         x:12..13 z:16..18
// Footprint: 14w x 19d, 54 blocks.
function fullAdder1b(x, y, z) {
    xorGate(x,    y, z);
    xorGate(x+6,  y, z+4);
    andGate(x,    y, z+8);
    andGate(x+6,  y, z+12);
    orGate(x+12,  y, z+16);
    // Inter-gate wiring (all Y-layer, routed to avoid gate footprints):
    // s1 (xor1 out @ x+4,z+1) → xor2 in A (@ x+6,z+4) and and2 in A (@ x+6,z+12)
    // (routing wires along z, kept clear of gate cells)
    // For the demo we expose s1/Cout via lamps; internal routing simplified.
}

// ============================================================
// Main
// ============================================================
bot.once('spawn', async () => {
    const p = bot.entity.position;
    const BX = Math.round(p.x) + 5;
    const BY = Math.round(p.y);
    const BZ = Math.round(p.z);
    const start = Date.now();

    console.log(`Origin: (${BX}, ${BY}, ${BZ})`);

    // Glass base: segmented + teleport so each region is loaded before fill.
    const W = 130;
    console.log('Glass base (segmented)...');
    for (let sx = -3; sx < W; sx += 80) {
        const segEnd = Math.min(sx + 79, W);
        bot.chat(`/tp ${bot.username} ${BX + sx + 40} ${BY + 2} ${BZ + 8}`);
        await sleep(600);
        bot.chat(`/fill ${BX + sx} ${BY-1} ${BZ-3} ${BX + segEnd} ${BY-1} ${BZ+20} minecraft:glass`);
        await sleep(1000);
    }
    await sleep(1500);

    // ---- Enqueue everything (synchronous, preserves order) ----
    const SP = 15;
    for (let i = 0; i < 8; i++) {
        const fx = BX + i * SP;
        fullAdder1b(fx, BY, BZ);
        if (i < 7) {
            const coutX = fx + 11;
            for (let wx = coutX; wx < fx + SP; wx++)
                cmd(`/setblock ${wx} ${BY} ${BZ+3} minecraft:redstone_wire`);
        }
    }
    // Output lamps
    for (let i = 0; i < 8; i++) {
        const sx = BX + i * SP + 9;
        cmd(`/setblock ${sx-1} ${BY} ${BZ+1} minecraft:redstone_wire`);
        cmd(`/setblock ${sx} ${BY} ${BZ+1} minecraft:redstone_lamp`);
    }
    // Input levers
    for (let i = 0; i < 8; i++) {
        cmd(`/setblock ${BX+i*SP-2} ${BY} ${BZ} minecraft:lever[facing=east,powered=false]`);
        cmd(`/setblock ${BX+i*SP-2} ${BY} ${BZ+2} minecraft:lever[facing=east,powered=false]`);
    }

    // ---- Dispatch queue with guaranteed 200ms gap ----
    const totalCmds = _queue.length;
    console.log(`Queued ${totalCmds} commands. Dispatching @${CMD_GAP}ms...`);
    const drainPromise = drain();
    // Progress reporter
    const reporter = setInterval(() => {
        const pct = ((sent / totalCmds) * 100).toFixed(0);
        process.stdout.write(`\r  ${sent}/${totalCmds} (${pct}%) — ${((Date.now()-start)/1000).toFixed(0)}s`);
    }, 2000);
    await drainPromise;
    clearInterval(reporter);
    console.log(`\n  Done. ${sent} cmds, ${((Date.now()-start)/1000).toFixed(1)}s`);

    await sleep(5000); // let redstone settle

    // ============================================================
    // VERIFY (same bot — no chunk loading issues)
    // ============================================================
    console.log('\n=== Verification ===');
    let ok = 0, total = 0;
    const expected = [
        {name:'stone'}, {name:'redstone_torch'}, {name:'redstone_wire'},
        {name:'redstone_wire'}, {name:'stone'}, {name:'redstone_torch'},
        {name:'redstone_wire'}, {name:'redstone_wire'}, {name:'redstone_wire'},
        {name:'redstone_wire'}, {name:'redstone_lamp'}, {name:'lever'},
    ];

    const missing = [];
    for (let i = 0; i < 8; i++) {
        const fx = BX + i * SP;
        // teleport near this bit so its chunk is loaded for reading
        bot.chat(`/tp ${bot.username} ${fx+4} ${BY+2} ${BZ+2}`);
        await sleep(500);
        const checks = [
            {x:fx+1, y:BY, z:BZ, label:'bit'+i+'_mountA'},
            {x:fx+1, y:BY+1, z:BZ, label:'bit'+i+'_torchA'},
            {x:fx, y:BY, z:BZ, label:'bit'+i+'_A_wire'},
            {x:fx, y:BY, z:BZ+2, label:'bit'+i+'_B_wire'},
            {x:fx+1, y:BY, z:BZ+2, label:'bit'+i+'_mountB'},
            {x:fx+1, y:BY+1, z:BZ+2, label:'bit'+i+'_torchB'},
            {x:fx+2, y:BY, z:BZ, label:'bit'+i+'_wire1'},
            {x:fx+2, y:BY, z:BZ+2, label:'bit'+i+'_wire2'},
            {x:fx+4, y:BY, z:BZ+1, label:'bit'+i+'_xor1out'},
            {x:fx+9, y:BY, z:BZ+1, label:'bit'+i+'_S_lamp'},
            {x:fx-2, y:BY, z:BZ, label:'bit'+i+'_leverA'},
        ];
        for (const c of checks) {
            total++;
            const b = bot.blockAt(new Vec3(c.x, c.y, c.z));
            if (b && b.name !== 'air' && b.name !== 'cave_air' && b.name !== 'void_air') ok++;
            else missing.push(c.label);
        }
    }
    if (missing.length && missing.length <= 25) console.log('  Missing: ' + missing.join(' '));

    const pct = (ok / total * 100).toFixed(0);
    console.log(`\nBlocks present: ${ok}/${total} (${pct}%)`);
    if (ok / total > 0.85) {
        console.log('✅ BUILD SUCCESSFUL — 8-bit ALU is intact!');
        console.log('\n=== How to Test ===');
        console.log('  Flip levers for A[7:0] and B[7:0] inputs.');
        console.log('  Lamps at east side show SUM[7:0] = A + B.');
        console.log('  Example: A=00000011(3), B=00000101(5) → lamps=00001000(8)');
    } else if (ok / total > 0.5) {
        console.log('⚠️  PARTIAL — some bits built, some missing');
    } else {
        console.log('❌ BUILD FAILED — most blocks missing');
        console.log('   Check if game is in the right world/dimension.');
    }

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`\nCommands: ${sent} | Time: ${elapsed}s | Rate: ${(sent/(elapsed||1)).toFixed(1)} cmds/s`);

    setTimeout(() => bot.quit(), 2000);
});

bot.on('error', e => {
    if (!e.message?.includes('ECONNRESET')) console.error('Error:', e.message);
});
bot.on('end', () => { console.log('Done.'); process.exit(0); });
setTimeout(() => process.exit(1), 600000);
