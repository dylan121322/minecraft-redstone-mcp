/**
 * build_display_pure.cjs — Pure Redstone Display v3
 *
 * KEY DESIGN: Y-stacked buses avoid crosstalk.
 *   - Bus 0 (smiley):  BY+1
 *   - Bus 1 (H):       BY+3
 *   - Bus 2 (heart):   BY+5
 *   - Bus 3 (checker): BY+7
 *
 * Each bus = redstone dust at its Y level, connecting observer output
 * to repeaters. Repeaters face DOWN into lamps directly below.
 *
 * Note_block → observer → vertical wire ↑ → bus dust → repeaters ↓ → lamps
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'PureV3', keepalive:false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const BX = -118, BY = 58, BZ = -53, GAP = 2, COLS = 8, ROWS = 8;

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
    console.log(`Pure Redstone Display v3 at (${BX},${BY},${BZ})`);

    // === Clear ===
    const W=(COLS-1)*GAP+2, D=(ROWS-1)*GAP+2;
    bot.chat(`/fill ${BX-6} ${BY-2} ${BZ-3} ${BX+W} ${BY+10} ${BZ+D} minecraft:air`);
    await sleep(1500);
    bot.chat(`/fill ${BX-6} ${BY-2} ${BZ-3} ${BX+W} ${BY-2} ${BZ+D} minecraft:glass`);
    await sleep(1500);

    // === LAMPS ===
    console.log('Phase 1: 64 lamps...');
    for (let r=0; r<ROWS; r++) {
        for (let c=0; c<COLS; c++)
            bot.chat(`/setblock ${BX+c*GAP} ${BY} ${BZ+r*GAP} minecraft:redstone_lamp`);
        await sleep(30);
    }
    await sleep(500);

    // === 4 BUSES (Y-stacked) ===
    // Each bus: BY+1, BY+3, BY+5, BY+7
    // At each bus level: redstone dust runs at (lampX, busY, lampZ)
    // Repeater from dust DOWN to lamp
    console.log('Phase 2: Y-stacked buses...');
    let totalReps = 0;

    for (let busIdx = 0; busIdx < 4; busIdx++) {
        const busY = BY + (busIdx * 2) + 1;  // BY+1, BY+3, BY+5, BY+7
        const pattern = PATTERNS[busIdx];

        // Place stone support at busY-1 for dust
        for (let r=0; r<ROWS; r++) {
            for (let c=0; c<COLS; c++) {
                const lx = BX + c*GAP, lz = BZ + r*GAP;
                if (pattern[7-r][c]) {
                    // Stone support
                    bot.chat(`/setblock ${lx} ${busY-1} ${lz} minecraft:stone`);
                    // Redstone dust at bus level
                    bot.chat(`/setblock ${lx} ${busY} ${lz} minecraft:redstone_wire`);
                    // Repeater from busY DOWN to lamp (lamp at BY)
                    // Repeater facing DOWN at (lx, busY, lz) outputs to (lx, busY-1, lz)
                    // Need to reach lamp at (lx, BY, lz)
                    // Chain of repeaters facing down:
                    for (let y = busY; y > BY; y--) {
                        bot.chat(`/setblock ${lx} ${y} ${lz} minecraft:repeater[facing=down,delay=1]`);
                    }
                    totalReps++;
                }
            }
        }

        // Connect dust horizontally between columns (for same-row same-bus pixels)
        for (let r=0; r<ROWS; r++) {
            const lz = BZ + r*GAP;
            let firstOn = -1, lastOn = -1;
            for (let c=0; c<COLS; c++) {
                if (pattern[7-r][c]) {
                    if (firstOn < 0) firstOn = c;
                    lastOn = c;
                }
            }
            if (firstOn >= 0) {
                // Fill dust between first and last ON pixel in this row
                for (let c=firstOn; c<=lastOn; c++) {
                    bot.chat(`/setblock ${BX+c*GAP} ${busY} ${lz} minecraft:redstone_wire`);
                }
            }
        }
        await sleep(300);
    }
    console.log(`  ${totalReps} pixels wired across 4 layers`);
    await sleep(500);

    // === CONTROLS ===
    console.log('Phase 3: Note_block controls...');
    for (let busIdx = 0; busIdx < 4; busIdx++) {
        const busY = BY + (busIdx * 2) + 1;
        const nz = BZ + busIdx * 4;
        const nx = BX - 5;

        // Note block
        bot.chat(`/setblock ${nx} ${BY} ${nz} minecraft:note_block`);
        bot.chat(`/setblock ${nx} ${BY-1} ${nz} minecraft:stone`);
        // Observer facing east (watches note_block)
        bot.chat(`/setblock ${nx+1} ${BY} ${nz} minecraft:observer[facing=west]`);

        // Wire UP from observer to bus level
        // Observer output at (nx+1, BY, nz) → vertical wire to (nx+1, busY, nz)
        for (let y = BY; y <= busY; y++) {
            bot.chat(`/setblock ${nx+1} ${y} ${nz} minecraft:stone`); // column support
        }
        // Redstone torch ladder: torches on alternating sides going up
        for (let y = BY; y < busY; y += 2) {
            bot.chat(`/setblock ${nx+2} ${y} ${nz} minecraft:redstone_torch[lit=true]`);
        }
        // Wire at bus level connecting to first lamp
        bot.chat(`/setblock ${nx+3} ${busY} ${nz} minecraft:redstone_wire`);
        // Horizontal wire to first lamp position
        const firstX = BX; // first lamp column
        for (let dx = nx+3; dx < firstX; dx++) {
            bot.chat(`/setblock ${dx} ${busY} ${nz} minecraft:redstone_wire`);
        }
        await sleep(100);
    }

    console.log(`\n✅ Pure Redstone Display built!`);
    console.log(`  Grid: ${ROWS}×${COLS} at (${BX},${BY},${BZ})`);
    console.log(`  4 Y-stacked buses at BY+1, BY+3, BY+5, BY+7`);
    console.log(`  Controls: 4 note_blocks at X=${BX-5}, Z=${BZ}+0/4/8/12`);
    console.log(`  Click note_block → observer → torch tower → bus → repeater chain → lamp`);
    bot.quit();
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
