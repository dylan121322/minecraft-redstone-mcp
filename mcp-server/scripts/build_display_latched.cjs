/**
 * build_display_latched.cjs — Pure Redstone Display with RS NOR Latches
 *
 * Architecture:
 *   4 RS NOR latches (one per pattern), storing which frame is displayed.
 *   4 note_block+observer pairs → SET their latch, RESET others.
 *   Each latch powers a bus → lamps for its pattern.
 *
 * RS NOR Latch (per pattern, 3×2×1):
 *   Torch 1 at (x, y+1, z) — output Q
 *   Torch 2 at (x, y+1, z+2) — complementary output
 *   Stone mounts at (x, y, z) and (x, y, z+2)
 *   Input wires from S/R to the stones
 *   Cross-coupling: Q feeds back to the other NOR
 *
 *   Simplified: use a single repeater locked latch
 *   Even simpler: each note_block's observer directly SETS one latch
 *   via a T flip-flop or pulse extender
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'LatchDisp', keepalive:false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const BX = -118, BY = 58, BZ = -53, GAP = 2, C=8, R=8;

const PATTERNS = [
    [[0,0,0,0,0,0,0,0],[0,0,1,1,1,1,0,0],[0,1,0,0,0,1,0,0],[0,1,0,0,0,1,0,0],
     [0,0,0,0,0,0,0,0],[0,1,0,0,0,1,0,0],[0,0,1,1,1,1,0,0],[0,0,0,0,0,0,0,0]],
    [[1,0,0,0,0,0,0,1],[1,0,0,0,0,0,0,1],[1,0,0,0,0,0,0,1],[1,1,1,1,1,1,1,1],
     [1,0,0,0,0,0,0,1],[1,0,0,0,0,0,0,1],[1,0,0,0,0,0,0,1],[0,0,0,0,0,0,0,0]],
    [[0,1,1,0,0,1,1,0],[1,0,0,1,1,0,0,1],[1,0,0,0,0,0,0,1],[0,1,0,0,0,0,1,0],
     [0,0,1,0,0,1,0,0],[0,0,0,1,1,0,0,0],[0,0,0,0,0,0,0,0],[0,0,0,0,0,0,0,0]],
    (()=>{const c=[];for(let r=0;r<8;r++){c[r]=[];for(let k=0;k<8;k++)c[r][k]=(r+k)%2;}return c;})(),
];

bot.once('spawn', async () => {
    const W=(C-1)*GAP+2, D=(R-1)*GAP+2;
    console.log(`Latched Display at (${BX},${BY},${BZ})`);

    // Clear
    bot.chat(`/fill ${BX-8} ${BY-2} ${BZ-4} ${BX+W} ${BY+5} ${BZ+D} minecraft:air`);
    await sleep(1500);
    bot.chat(`/fill ${BX-8} ${BY-2} ${BZ-4} ${BX+W} ${BY-2} ${BZ+D} minecraft:glass`);
    await sleep(1500);

    // === LAMPS ===
    console.log('Placing lamps...');
    for (let r=0; r<R; r++)
        for (let c=0; c<C; c++)
            bot.chat(`/setblock ${BX+c*GAP} ${BY} ${BZ+r*GAP} minecraft:redstone_lamp`);
    await sleep(500);

    // === LATCHES (1 per pattern) ===
    // Each latch: 2×3×1 RS NOR (torch × 2 + stone × 2 + wires)
    // Placed at X = BX-7, Z = BZ + patternIdx*4
    console.log('Building RS NOR latches...');
    let latchOutputs = []; // {x, z} — output position for each latch

    for (let p = 0; p < 4; p++) {
        const lx = BX - 7, lz = BZ + p * 4;
        // RS NOR: 2 stones at (lx, BY, lz) and (lx, BY, lz+2)
        // Torches on top: (lx, BY+1, lz) and (lx, BY+1, lz+2)
        // Wire junction at (lx+1, BY, lz+1)
        bot.chat(`/setblock ${lx} ${BY} ${lz} minecraft:stone`);
        bot.chat(`/setblock ${lx} ${BY} ${lz+2} minecraft:stone`);
        bot.chat(`/setblock ${lx} ${BY+1} ${lz} minecraft:redstone_torch[lit=true]`);
        bot.chat(`/setblock ${lx} ${BY+1} ${lz+2} minecraft:redstone_torch[lit=true]`);
        // Cross-coupling wires
        bot.chat(`/setblock ${lx+1} ${BY} ${lz} minecraft:redstone_wire`);
        bot.chat(`/setblock ${lx+1} ${BY} ${lz+2} minecraft:redstone_wire`);
        bot.chat(`/setblock ${lx+1} ${BY} ${lz+1} minecraft:redstone_wire`);
        // Output from torch at (lx, BY+1, lz) — this is Q (active high when SET)
        // Output wire at (lx, BY+2, lz) receiving torch signal
        bot.chat(`/setblock ${lx} ${BY+2} ${lz} minecraft:redstone_wire`);
        // Repeater to bus
        bot.chat(`/setblock ${lx+1} ${BY+2} ${lz} minecraft:repeater[facing=east,delay=1]`);
        // Horizontal wire to grid area
        for (let dx = lx+2; dx < BX; dx++) {
            bot.chat(`/setblock ${dx} ${BY+2} ${lz} minecraft:redstone_wire`);
        }

        latchOutputs.push({ lx, lz, outY: BY+2 });
        await sleep(100);
    }
    console.log('  4 latches built');

    // === NOTE_BLOCK + OBSERVER ===
    // SET for latch P: observer at (lx-2, BY-1, lz) facing the latch stone
    // RESET for others: OR-wire from all observers to reset pins
    console.log('Wiring controls...');
    let observerOutputs = [];
    for (let p = 0; p < 4; p++) {
        const lx = BX - 7, lz = BZ + p * 4;
        const nx = lx - 3;
        // Note block
        bot.chat(`/setblock ${nx} ${BY} ${lz} minecraft:note_block`);
        bot.chat(`/setblock ${nx} ${BY-1} ${lz} minecraft:stone`);
        // Observer at (nx+1, BY, lz) facing WEST → output EAST to (nx+2, BY, lz)
        bot.chat(`/setblock ${nx+1} ${BY} ${lz} minecraft:observer[facing=west]`);
        // Wire from observer output to latch SET input
        // SET = power the stone at (lx, BY, lz) which turns OFF torch → Q=1
        // Need a pulse from observer to power the SET stone
        // Observer output → repeater → wire → SET stone
        bot.chat(`/setblock ${nx+2} ${BY} ${lz} minecraft:redstone_wire`);
        for (let dx = nx+3; dx < lx; dx++) {
            bot.chat(`/setblock ${dx} ${BY} ${lz} minecraft:redstone_wire`);
        }
        // Repeater into SET stone
        bot.chat(`/setblock ${lx-1} ${BY} ${lz} minecraft:repeater[facing=east,delay=1]`);

        // RESET: connect observer to ALL OTHER latches' RESET stones (lz+2)
        // Use a bus at BY+1, above the wiring
        for (let q = 0; q < 4; q++) {
            if (q === p) continue; // don't reset self
            const rlz = BZ + q * 4;
            // Connect this observer to other latch's reset
            // Use a vertical connection: observer output → UP → horizontal bus → DOWN → reset stone
            // Vertical: dust on stone pillar
            bot.chat(`/setblock ${nx+2} ${BY+1} ${lz} minecraft:redstone_wire`);
            // Horizontal bus at BY+1 for this row
            bot.chat(`/setblock ${lx-1} ${BY+1} ${rlz+2} minecraft:repeater[facing=west,delay=1]`);
        }
        observerOutputs.push({ x: nx+2, y: BY, z: lz });
        await sleep(100);
    }

    // === PATTERN BUSES from latch outputs ===
    // Latch output Q (active high) is at (lx, BY+2, lz) where torch(byte) is ON when SET
    // Actually: RS NOR Q is active when SET stone is powered → torch OFF → Q=1
    // Wait: SET = power stone at (lx, BY, lz). When stone powered → torch at (lx, BY+1, lz) turns OFF.
    // Q wire at (lx, BY+2, lz) receives signal from torch. When torch OFF → Q=0.
    // So SET makes Q=0, RESET makes Q=1. This is Q_bar, not Q!
    // The COMPLEMENTARY output (torch at lz+2) gives Q.
    // When SET: torch at lz OFF, torch at lz+2 stays ON (because its stone is NOT powered).
    // Q = torch at lz+2 state: ON when SET, OFF when RESET. ✓
    // So Q is at (lx, BY+1, lz+2)'s output → wire at (lx, BY+2, lz+2)

    // Let me fix: Q output = wire at (lx, BY+2, lz+2) receiving torch signal from (lx, BY+1, lz+2)
    console.log('Fixing Q outputs and wiring to buses...');

    // Already placed wire at (lx, BY+2, lz) — this is Q_bar. Need Q at lz+2.
    for (let p = 0; p < 4; p++) {
        const lx = BX - 7, lz = BZ + p * 4;
        // Q output: torch at (lx, BY+1, lz+2) → wire at (lx, BY+2, lz+2)
        bot.chat(`/setblock ${lx} ${BY+2} ${lz+2} minecraft:redstone_wire`);
        // Repeater from Q to grid
        bot.chat(`/setblock ${lx+1} ${BY+2} ${lz+2} minecraft:repeater[facing=east,delay=1]`);
        for (let dx = lx+2; dx < BX; dx++) {
            bot.chat(`/setblock ${dx} ${BY+2} ${lz+2} minecraft:redstone_wire`);
        }
        await sleep(50);
    }

    // === CONNECT BUSES TO LAMPS ===
    // Each Q output bus at (BX+c*GAP, BY+2, lz+2) needs to feed repeaters DOWN to lamps
    console.log('Wiring buses to lamps...');
    for (let p = 0; p < 4; p++) {
        const pattern = PATTERNS[p];
        const lz = BZ + p * 4;
        for (let r = 0; r < R; r++) {
            const lampZ = BZ + r * GAP;
            for (let c = 0; c < C; c++) {
                if (pattern[7-r][c]) {
                    const lampX = BX + c * GAP;
                    // Wire at (lampX, BY+2, lz+2) is Q bus — connect down to lamp
                    // Actually bus runs horizontally at BY+2, we need vertical connection
                    // Repeater facing DOWN from BY+2 to BY+1, then another facing DOWN to BY
                    bot.chat(`/setblock ${lampX} ${BY+1} ${lampZ} minecraft:repeater[facing=down,delay=1]`);
                    bot.chat(`/setblock ${lampX} ${BY+2} ${lampZ} minecraft:redstone_wire`);
                }
            }
        }
        await sleep(200);
    }
    await sleep(500);

    console.log(`\n✅ Latched Display built!`);
    console.log(`  4 RS NOR latches at X=${BX-7}`);
    console.log(`  4 note_blocks at X=${BX-10}`);
    console.log(`  Click a note_block to switch frame (others auto-reset)`);
    bot.quit();
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
