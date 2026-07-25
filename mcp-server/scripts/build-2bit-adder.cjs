#!/usr/bin/env node
/**
 * build-2bit-adder.js — Directly build a 2-bit ripple-carry adder in Minecraft
 * Usage: node build-2bit-adder.js [bx by bz] [--dry-run]
 */

const mineflayer = require('mineflayer');

const HOST = 'localhost';
const PORT = 44508;
const USERNAME = 'RedstoneBot2';

// Base position
const BX = parseInt(process.argv[2]) || 0;
const BY = parseInt(process.argv[3]) || 64;
const BZ = parseInt(process.argv[4]) || 0;
const DRY_RUN = process.argv.includes('--dry-run');

// Circuit blocks for one half-adder stage (A+B → S, C)
// Returns blocks with RELATIVE positions [dx, dy, dz] from stage origin
function halfAdderBlocks() {
    // Verified layout matching buildRedstoneCircuit.ts HALF_ADDER template
    // AND = NOT(OR(NOT(A), NOT(B))) for Carry
    // XOR = (A OR B) AND NOT(A AND B) for Sum
    return [
        // Inputs
        { p: [0, 0, 0], b: 'minecraft:redstone_wire' },
        { p: [0, 0, 2], b: 'minecraft:redstone_wire' },
        // NOT A: block+torch
        { p: [1, 0, 0], b: 'minecraft:stone' },
        { p: [1, 1, 0], b: 'minecraft:redstone_torch[lit=true]' },
        // NOT B: block+torch
        { p: [1, 0, 2], b: 'minecraft:stone' },
        { p: [1, 1, 2], b: 'minecraft:redstone_torch[lit=true]' },
        // Junction: merges NOT A and NOT B (OR of inverted inputs)
        { p: [1, 0, 1], b: 'minecraft:redstone_wire' },
        // Wires carrying NOT A and NOT B outputs
        { p: [2, 0, 0], b: 'minecraft:redstone_wire' },
        { p: [2, 0, 2], b: 'minecraft:redstone_wire' },
        // Middle inverter: NOT(OR(NOT A, NOT B)) = AND
        { p: [2, 0, 1], b: 'minecraft:stone' },
        { p: [2, 1, 1], b: 'minecraft:redstone_torch[lit=true]' },
        // Second inverter (XOR layer): NOT(AND)
        { p: [3, 0, 1], b: 'minecraft:stone' },
        { p: [3, 1, 1], b: 'minecraft:redstone_torch[lit=true]' },
        // Carry wires from AND output
        { p: [3, 0, 0], b: 'minecraft:redstone_wire' },
        { p: [3, 0, 2], b: 'minecraft:redstone_wire' },
        // Final output wires
        { p: [4, 0, 0], b: 'minecraft:redstone_wire' },
        { p: [4, 0, 2], b: 'minecraft:redstone_wire' },
        // Output pads (S at X+1, C at X+1)
        { p: [5, 0, 0], b: 'minecraft:redstone_wire' },
        { p: [5, 0, 2], b: 'minecraft:redstone_wire' },
    ];
}

// Full circuit: HA(A0,B0) + HA(A1,B1) with carry routing
// Uses relative positions, offset by (bx, by, bz)
function build2BitAdderBlocks(bx, by, bz) {
    const blocks = [];
    const spacing = 7;

    // Stage 0: Half Adder for LSB at (bx, by, bz)
    for (const { p, b } of halfAdderBlocks()) {
        blocks.push({ p: [bx+p[0], by+p[1], bz+p[2]], b });
    }

    // Stage 1: Half Adder for MSB at (bx+spacing, by, bz)
    for (const { p, b } of halfAdderBlocks()) {
        blocks.push({ p: [bx+spacing+p[0], by+p[1], bz+p[2]], b });
    }

    // Carry: Stage0 C-output → Stage1 B-input via repeater isolation
    // Stage0 carry out is at X=bx+5, Z=bz+2 (relative pos [5, 0, 2])
    const carryStartX = bx + 5;
    blocks.push({ p: [carryStartX, by, bz+2], b: 'minecraft:repeater[facing=east,delay=1]' });
    blocks.push({ p: [carryStartX+1, by, bz+2], b: 'minecraft:redstone_wire' });

    return blocks;
}

function build(bot, buildY) {
    const blocks = build2BitAdderBlocks(BX, buildY, BZ);
    console.log(`Building 2-bit adder at (${BX}, ${buildY}, ${BZ})`);
    console.log(`Total blocks: ${blocks.length}`);

    if (DRY_RUN) {
        console.log('\n=== DRY RUN — Commands that would be sent ===');
        for (const { p, b } of blocks) {
            const [ax, ay, az] = p;
            const cmd = `/setblock ${Math.floor(ax)} ${Math.floor(ay)} ${Math.floor(az)} ${b}`;
            console.log(cmd);
        }
        console.log(`\nTotal: ${blocks.length} commands`);
        bot.quit();
        return;
    }

    let i = 0;
    const spacing = 7;
    const interval = setInterval(() => {
        if (i >= blocks.length) {
            clearInterval(interval);
            console.log(`\n✅ Build complete! ${blocks.length} blocks placed.`);
            console.log('Test inputs:');
            console.log('  Place levers at:');
            console.log(`    A0: (${BX}, ${buildY}, ${BZ})`);
            console.log(`    B0: (${BX}, ${buildY}, ${BZ+2})`);
            console.log(`    A1: (${BX+spacing}, ${buildY}, ${BZ})`);
            console.log(`    B1: (${BX+spacing}, ${buildY}, ${BZ+2})`);
            console.log('  Outputs (place redstone lamps to see):');
            console.log(`    S0: (${BX+5}, ${buildY}, ${BZ})`);
            console.log(`    S1: (${BX+spacing+5}, ${buildY}, ${BZ})`);
            console.log(`    Cout: (${BX+spacing+5}, ${buildY}, ${BZ+2})`);
            setTimeout(() => bot.quit(), 30000);
            return;
        }

        const { p, b } = blocks[i];
        const [ax, ay, az] = p;  // absolute coordinates
        const cmd = `/setblock ${Math.floor(ax)} ${Math.floor(ay)} ${Math.floor(az)} ${b}`;
        bot.chat(cmd);
        if (i % 5 === 0) process.stdout.write(`\r  Placed ${i}/${blocks.length}...`);
        i++;
    }, 150); // ~7 blocks/sec to avoid rate limiting
}

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME });

bot.once('spawn', () => {
    // Auto-detect ground level from spawn position
    const groundY = Math.floor(bot.entity.position.y);
    const buildY = process.argv[4] ? parseInt(process.argv[4]) : groundY;
    console.log(`Bot spawned at Y=${groundY}, building at Y=${buildY}`);

    // Update BY for the build
    // Override command-line BY with detected ground level
    process.env.BUILD_Y = String(buildY);
    build(bot, buildY);
});

bot.on('error', err => { console.error('Bot error:', err.message); process.exit(1); });
bot.on('kicked', reason => { console.error('Kicked:', reason); process.exit(1); });
bot.on('end', () => { console.log('Disconnected.'); process.exit(0); });

setTimeout(() => { console.error('Timeout — failed to connect'); process.exit(1); }, 30000);
