/**
 * build_display_pure_v4.cjs — Pure Redstone 4-Frame Display (RS NOR Latches)
 *
 * Architecture:
 *   - 4 RS NOR latches (2 torches + 2 stones + wires each)
 *   - 4 note_block + observer pairs
 *   - Observer output → split: RESET all latches (fast) + SET own latch (delayed 2rt)
 *   - Each latch Q drives a bus → repeaters → lamps
 *   - Buses at Y+2 (above lamps), each at different Z offset to avoid crosstalk
 *
 * RS NOR latch (per pattern, 3 blocks wide):
 *   [stone A] [wire_junction] [stone B]     ← Y level
 *   [torch A]             [torch B]          ← Y+1
 *
 *   SET input: wire to stone A → torch A OFF → Q=1 (active when SET)
 *   RESET input: wire to stone B → torch B OFF → !Q=0 → Q=0
 *   Cross-coupling: torch A output → stone B, torch B output → stone A
 *   Q output: wire from torch B (lit when SET, off when RESET)
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'PureV4', keepalive:false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const BX = -118, BY = 58, BZ = -53, G=2, C=8, R=8;

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
    const W=(C-1)*G+2, D=(R-1)*G+2;
    console.log(`Pure RS NOR Display at (${BX},${BY},${BZ})`);

    // Clear
    bot.chat(`/fill ${BX-8} ${BY-2} ${BZ-4} ${BX+W} ${BY+4} ${BZ+D} minecraft:air`);
    await sleep(1500);
    bot.chat(`/fill ${BX-8} ${BY-2} ${BZ-4} ${BX+W} ${BY-2} ${BZ+D} minecraft:glass`);
    await sleep(1500);

    // === LAMPS ===
    console.log('Phase 1: Lamps & stone support...');
    for (let r=0; r<R; r++)
        for (let c=0; c<C; c++) {
            bot.chat(`/setblock ${BX+c*G} ${BY} ${BZ+r*G} minecraft:redstone_lamp`);
            bot.chat(`/setblock ${BX+c*G} ${BY-1} ${BZ+r*G} minecraft:stone`);
        }
    await sleep(800);

    // === RS NOR LATCHES (4×) ===
    // Latch at Z = BZ + p*4, X = BX - 4
    // Two stones at X-4, X-2 (gap for wire junction at X-3)
    console.log('Phase 2: RS NOR latches...');
    let latchQ = []; // [{x, y, z}] — Q output position for each latch

    for (let p = 0; p < 4; p++) {
        const lx = BX - 4, lz = BZ + p * 4;
        // Stone A (SET side) at (lx, BY, lz)
        bot.chat(`/setblock ${lx} ${BY} ${lz} minecraft:stone`);
        // Stone B (RESET side) at (lx+2, BY, lz)
        bot.chat(`/setblock ${lx+2} ${BY} ${lz} minecraft:stone`);
        // Torch A on stone A: (lx, BY+1, lz)
        bot.chat(`/setblock ${lx} ${BY+1} ${lz} minecraft:redstone_torch[lit=true]`);
        // Torch B on stone B: (lx+2, BY+1, lz) — this is Q (active when SET)
        bot.chat(`/setblock ${lx+2} ${BY+1} ${lz} minecraft:redstone_torch[lit=true]`);
        // Wire junction between stones at (lx+1, BY, lz)
        bot.chat(`/setblock ${lx+1} ${BY} ${lz} minecraft:redstone_wire`);
        // Cross-coupling: torch A output → wire to stone B's back
        bot.chat(`/setblock ${lx} ${BY+2} ${lz} minecraft:redstone_wire`);
        bot.chat(`/setblock ${lx+1} ${BY+2} ${lz} minecraft:repeater[facing=east,delay=1]`);
        bot.chat(`/setblock ${lx+2} ${BY+2} ${lz} minecraft:redstone_wire`);
        // Cross-coupling: torch B output → wire to stone A's back
        bot.chat(`/setblock ${lx+2} ${BY+2} ${lz+1} minecraft:redstone_wire`);
        bot.chat(`/setblock ${lx+1} ${BY+2} ${lz+1} minecraft:repeater[facing=west,delay=1]`);
        bot.chat(`/setblock ${lx} ${BY+2} ${lz+1} minecraft:redstone_wire`);

        // Q output: torch B (lx+2, BY+1, lz) → wire at (lx+3, BY+1, lz)
        bot.chat(`/setblock ${lx+3} ${BY+1} ${lz} minecraft:redstone_wire`);
        // Repeater from Q into bus
        bot.chat(`/setblock ${lx+3} ${BY+1} ${lz} minecraft:repeater[facing=east,delay=1]`);
        // Bus wire: runs at BY+1, connecting Q to all lamp positions
        for (let dx = lx+4; dx < BX; dx++)
            bot.chat(`/setblock ${dx} ${BY+1} ${lz} minecraft:redstone_wire`);

        latchQ.push({ x: lx+3, y: BY+1, z: lz });
        await sleep(100);
    }
    console.log('  4 latches built');

    // === NOTE_BLOCK + OBSERVER + TIMING ===
    // Note_block at X-7, observer at X-6 facing WEST
    // Observer output → split into RESET (fast) and SET (delayed)
    // RESET: direct wire to ALL latch B stones
    // SET: delayed 2rt (2 repeaters)
    console.log('Phase 3: Controls with timing...');
    for (let p = 0; p < 4; p++) {
        const lz = BZ + p * 4;
        const nx = BX - 7;
        // Note block
        bot.chat(`/setblock ${nx} ${BY} ${lz} minecraft:note_block`);
        bot.chat(`/setblock ${nx} ${BY-1} ${lz} minecraft:stone`);
        // Observer at (nx+1, BY, lz) facing WEST
        bot.chat(`/setblock ${nx+1} ${BY} ${lz} minecraft:observer[facing=west]`);
        // Observer output at (nx+2, BY, lz) → split point
        bot.chat(`/setblock ${nx+2} ${BY} ${lz} minecraft:redstone_wire`);

        // === RESET path (fast): connects to ALL latch B stones ===
        // Wire from observer output to all 4 latches' RESET stones
        for (let q = 0; q < 4; q++) {
            const rlz = BZ + q * 4;
            // RESET input goes to stone B at (BX-2, BY, rlz)
            bot.chat(`/setblock ${BX-3} ${BY} ${rlz} minecraft:repeater[facing=west,delay=1]`);
            // Horizontal RESET bus at BY (all latches share this)
            for (let dx = nx+2; dx < BX-3; dx++)
                bot.chat(`/setblock ${dx} ${BY} ${rlz} minecraft:redstone_wire`);
        }

        // === SET path (delayed 2rt): connects ONLY to latch P's stone A ===
        // Observer → delay chain → stone A at (BX-4, BY, lz)
        bot.chat(`/setblock ${nx+2} ${BY+1} ${lz} minecraft:repeater[facing=up,delay=2]`);
        bot.chat(`/setblock ${nx+2} ${BY+2} ${lz} minecraft:repeater[facing=east,delay=1]`);
        for (let dx = nx+3; dx < BX-4; dx++)
            bot.chat(`/setblock ${dx} ${BY+2} ${lz} minecraft:redstone_wire`);
        // Repeater into SET stone
        bot.chat(`/setblock ${BX-5} ${BY+2} ${lz} minecraft:repeater[facing=east,delay=1]`);
        // Wire down to SET stone level
        bot.chat(`/setblock ${BX-4} ${BY+1} ${lz-1} minecraft:redstone_wire`);
        bot.chat(`/setblock ${BX-4} ${BY} ${lz-1} minecraft:repeater[facing=south,delay=1]`);

        await sleep(100);
    }

    // === BUS TO LAMP CONNECTIONS ===
    // Each Q bus at (BX+c*G, BY+1, lz) feeds repeaters DOWN to lamps
    console.log('Phase 4: Bus→lamp connections...');
    for (let p = 0; p < 4; p++) {
        const pattern = PATTERNS[p];
        const busZ = BZ + p * 4;
        for (let r = 0; r < R; r++) {
            const lampZ = BZ + r * G;
            for (let c = 0; c < C; c++) {
                if (pattern[7-r][c]) {
                    const lx = BX + c * G;
                    // Repeater from bus (at BY+1, lx, busZ) DOWN to lamp (at BY, lx, lampZ)
                    // Bus runs at BY+1 horizontally. At each lamp X position,
                    // we need a vertical connection from bus to lamp.
                    // Repeater at (lx, BY+1, lampZ) facing DOWN ← this connects to lamp
                    // But bus is at Z=busZ, lamp at Z=lampZ. Need horizontal connection too.
                    // Use dust at BY+1 from busZ to lampZ, then repeater facing DOWN
                    bot.chat(`/setblock ${lx} ${BY+1} ${busZ} minecraft:redstone_wire`);
                    // Extend dust from busZ to lampZ
                    const zStart = Math.min(busZ, lampZ), zEnd = Math.max(busZ, lampZ);
                    for (let z = zStart; z <= zEnd; z++)
                        bot.chat(`/setblock ${lx} ${BY+1} ${z} minecraft:redstone_wire`);
                    // Repeater facing DOWN at (lx, BY+1, lampZ) → lamp
                    bot.chat(`/setblock ${lx} ${BY} ${lampZ} minecraft:repeater[facing=up,delay=1]`);
                }
            }
        }
        await sleep(200);
    }

    console.log(`\n✅ Pure Redstone RS NOR Display built!`);
    console.log(`  4 RS NOR latches at X=${BX-4}`);
    console.log(`  4 note_blocks at X=${BX-7}`);
    console.log(`  Click note_block → RESET all (fast) → SET one (delayed)`);
    bot.quit();
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
