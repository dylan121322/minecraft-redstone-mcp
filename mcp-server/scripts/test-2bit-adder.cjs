#!/usr/bin/env node
/**
 * test-2bit-adder.cjs — Auto-test a 2-bit adder circuit
 * Usage: node test-2bit-adder.cjs [bx bz] [--no-build]
 *
 * Steps:
 * 1. Place redstone lamps at output positions (S0, S1, Cout)
 * 2. Iterate all 16 input combinations (0-3 + 0-3)
 * 3. For each: set inputs with redstone blocks, read lamp states
 * 4. Compare actual vs expected, report PASS/FAIL
 */

const mineflayer = require('mineflayer');

const HOST = 'localhost';
const PORT = process.env.PORT || 44508;
const USERNAME = 'TesterBot';
const BX = parseInt(process.argv[2]) || 0;
const BZ = parseInt(process.argv[3]) || 2;
const NO_BUILD = process.argv.includes('--no-build');

// Circuit layout (must match build-2bit-adder.cjs)
const SPACING = 7;
const OUTPUTS = {
    S0:   [BX + 5,          0, BZ],        // [x, y, z] — y filled at runtime
    C0:   [BX + 5,          0, BZ + 2],
    S1:   [BX + 5 + SPACING, 0, BZ],
    Cout: [BX + 5 + SPACING, 0, BZ + 2],
};
const INPUTS = {
    A0: [BX,           0, BZ],
    B0: [BX,           0, BZ + 2],
    A1: [BX + SPACING, 0, BZ],
    B1: [BX + SPACING, 0, BZ + 2],
};

function truthTable2Bit() {
    const cases = [];
    for (let a = 0; a < 4; a++) {
        for (let b = 0; b < 4; b++) {
            const result = a + b;
            cases.push({
                label: `${a}+${b}`,
                inputs: { A0: (a >> 0) & 1, B0: (b >> 0) & 1, A1: (a >> 1) & 1, B1: (b >> 1) & 1 },
                expected: { S0: (result >> 0) & 1, S1: (result >> 1) & 1, Cout: (result >> 2) & 1 },
            });
        }
    }
    return cases;
}

async function setInput(bot, buildY, name, value) {
    const [x, , z] = INPUTS[name];
    const pos = { x, y: buildY, z };
    if (value === 1) {
        // Redstone block = constant power source
        await placeBlock(bot, pos, 'minecraft:redstone_block');
    } else {
        await placeBlock(bot, pos, 'minecraft:air');
    }
}

async function placeBlock(bot, pos, block) {
    if (block === 'minecraft:air') {
        const existing = bot.blockAt(new Vec3(pos.x, pos.y, pos.z));
        if (existing && existing.name !== 'air') {
            bot.chat(`/setblock ${pos.x} ${pos.y} ${pos.z} minecraft:air destroy`);
        }
    } else {
        bot.chat(`/setblock ${pos.x} ${pos.y} ${pos.z} ${block}`);
    }
    await sleep(300);
}

function readOutput(bot, buildY, name) {
    const [x, , z] = OUTPUTS[name];
    // Read redstone_wire power level directly at circuit Y level
    const pos = new Vec3(x, buildY, z);
    const block = bot.blockAt(pos);
    if (!block) return null;
    if (block.name === 'redstone_wire') {
        const props = block.getProperties ? block.getProperties() : {};
        const power = parseInt(props.power || '0');
        return power > 0 ? 1 : 0;
    }
    // Wire might be replaced — try one block above
    const posAbove = new Vec3(x, buildY + 1, z);
    const blockAbove = bot.blockAt(posAbove);
    if (blockAbove && blockAbove.name === 'redstone_wire') {
        const props = blockAbove.getProperties ? blockAbove.getProperties() : {};
        const power = parseInt(props.power || '0');
        return power > 0 ? 1 : 0;
    }
    return null;
}

async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

function Vec3(x, y, z) { return { x, y, z, floored: () => ({ x: Math.floor(x), y: Math.floor(y), z: Math.floor(z) }) }; }

async function runTests(bot, buildY) {
    console.log(`\n=== Auto-Testing 2-bit Adder at Y=${buildY} ===\n`);

    // Output is directly read from the circuit's redstone wire at Y=buildY
    // No lamps needed — we read the wire power level directly
    console.log('Reading output directly from circuit wires...');

    console.log('Starting test sequence...\n');
    await sleep(1000);

    const cases = truthTable2Bit();
    let passed = 0;
    let failed = 0;
    const failures = [];

    for (const tc of cases) {
        // Set all inputs
        for (const [name, val] of Object.entries(tc.inputs)) {
            await setInput(bot, buildY, name, val);
        }

        // Wait for redstone propagation (torch chain = 4rt = 8gt = 400ms, add margin)
        await sleep(1200);

        // Read all outputs directly from circuit wires at Y=buildY
        const actual = {};
        for (const name of ['S0', 'S1', 'Cout']) {
            const val = readOutput(bot, buildY, name);
            actual[name] = val !== null ? val : 0;
            if (val === null) process.stdout.write('?');
        }

        // Compare
        let match = true;
        const mismatch = [];
        for (const name of ['S0', 'S1', 'Cout']) {
            if (actual[name] !== tc.expected[name]) {
                match = false;
                mismatch.push(`${name}: got ${actual[name]}, expected ${tc.expected[name]}`);
            }
        }

        if (match) {
            passed++;
            if (passed % 4 === 1) process.stdout.write('.');
        } else {
            failed++;
            failures.push({ test: tc.label, actual, expected: tc.expected, mismatch });
            process.stdout.write('✗');
        }
    }

    // Cleanup: remove input redstone blocks
    for (const name of Object.keys(INPUTS)) {
        await setInput(bot, buildY, name, 0);
    }

    console.log('\n');
    console.log('═'.repeat(50));
    console.log(`RESULTS: ${passed}/${passed + failed} passed`);
    if (failed > 0) {
        console.log(`\n${failed} FAILURES:`);
        for (const f of failures) {
            console.log(`  ${f.test}: ${f.mismatch.join(', ')}`);
        }
    } else {
        console.log('✅ All 16 test cases passed! Circuit is correct.');
    }
    console.log('═'.repeat(50));

    // Stay connected briefly then quit
    setTimeout(() => bot.quit(), 5000);
}

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME });

bot.once('spawn', async () => {
    const buildY = Math.floor(bot.entity.position.y);
    console.log(`TesterBot connected at Y=${buildY}`);
    await sleep(1000); // Wait for world to load
    await runTests(bot, buildY);
});

bot.on('error', err => { if (!err.message.includes('read ECONNRESET')) console.error('Error:', err.message); });
bot.on('kicked', reason => { console.error('Kicked:', JSON.stringify(reason)); process.exit(1); });
bot.on('end', () => { console.log('Disconnected.'); process.exit(0); });

setTimeout(() => { console.error('Connection timeout'); process.exit(1); }, 60000);
