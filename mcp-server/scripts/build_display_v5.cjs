/**
 * build_display_v5.cjs — Pure Redstone Display (Fixed RS NOR)
 *
 * Key fix: ALL blocks placed in Y-order, stones before torches.
 * Minimal RS NOR: 2 stones + 2 torches + 1 dust junction.
 *
 * RS NOR per pattern (X-offset +0):
 *   Y+1: [torch_A]           [torch_B]
 *   Y+0: [stone_A] [dust] [stone_B]
 *
 *   SET: power stone_A → torch_A OFF → Q=1 (torch_B stays ON)
 *   RST: power stone_B → torch_B OFF → Q=0 (torch_A turns ON)
 *
 * BUS: Q output from torch_B → repeater chain → lamps
 * TIMING: observer → split → FAST reset bus → DELAYED set (2rt)
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'V5Disp', keepalive:false });
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
    console.log(`v5 Display at (${BX},${BY},${BZ})`);

    // === FULL CLEAR + GLASS BASE ===
    bot.chat(`/fill ${BX-10} ${BY-2} ${BZ-6} ${BX+W} ${BY+4} ${BZ+D} minecraft:air`);
    await sleep(2000);
    bot.chat(`/fill ${BX-10} ${BY-2} ${BZ-6} ${BX+W} ${BY-2} ${BZ+D} minecraft:glass`);
    await sleep(2000);

    // ========================================
    // Y=BY-1: Stone supports for lamps
    // ========================================
    console.log('Y=BY-1: Stone supports...');
    for (let r=0; r<R; r++)
        for (let c=0; c<C; c++)
            bot.chat(`/setblock ${BX+c*G} ${BY-1} ${BZ+r*G} minecraft:stone`);
    // Also supports for latches and wiring
    for (let z=BZ-4; z<BZ+D; z++)
        for (let x=BX-10; x<BX+W; x++)
            bot.chat(`/setblock ${x} ${BY-1} ${z} minecraft:stone`);
    await sleep(1000);

    // ========================================
    // Y=BY: Stones + Wiring + Lamps
    // ========================================
    console.log('Y=BY: Lamps...');
    for (let r=0; r<R; r++)
        for (let c=0; c<C; c++)
            bot.chat(`/setblock ${BX+c*G} ${BY} ${BZ+r*G} minecraft:redstone_lamp`);
    await sleep(500);

    // === RS NOR LATCHES (at Y=BY, Y+1) ===
    // Latch P at Z = BZ + p*4, X = BX-4
    // Stone A at (BX-4, BY, z), Stone B at (BX-2, BY, z)
    // Dust junction at (BX-3, BY, z)
    console.log('Y=BY: Latch stones + dust...');
    for (let p=0; p<4; p++) {
        const z = BZ + p*4;
        bot.chat(`/setblock ${BX-4} ${BY} ${z} minecraft:stone`);     // stone A
        bot.chat(`/setblock ${BX-2} ${BY} ${z} minecraft:stone`);     // stone B
        bot.chat(`/setblock ${BX-3} ${BY} ${z} minecraft:redstone_wire`); // junction dust
        await sleep(50);
    }

    // === BUS WIRING (Y=BY, from latch Q to lamps) ===
    // Q = torch B state. Torch B at (BX-2, BY+1, z)
    // Torch B output → powers (BX-1, BY+1, z) → need to bring to lamps
    // Repeater at (BX-1, BY, z) facing EAST — reads from stone B which is strongly powered by torch B
    console.log('Y=BY: Bus repeaters...');
    for (let p=0; p<4; p++) {
        const pattern = PATTERNS[p];
        const z = BZ + p*4;

        // Q output: repeater at (BX-1, BY, z) facing east → wire → lamp area
        bot.chat(`/setblock ${BX-1} ${BY} ${z} minecraft:repeater[facing=east,delay=1]`);
        // Bus wire running east
        for (let dx=0; dx<W+2; dx++)
            bot.chat(`/setblock ${BX+dx} ${BY} ${z} minecraft:redstone_wire`);

        // Connect bus to lamps: at each lamp column, dust runs from busZ to lampZ
        for (let r=0; r<R; r++) {
            const lampZ = BZ + r*G;
            if (z !== lampZ) {
                // Dust from bus row to lamp row
                const zMin=Math.min(z,lampZ), zMax=Math.max(z,lampZ);
                for (let cz=zMin; cz<=zMax; cz++)
                    bot.chat(`/setblock ${BX} ${BY} ${cz} minecraft:redstone_wire`);
            }
            for (let c=0; c<C; c++) {
                if (pattern[7-r][c]) {
                    const lx = BX + c*G;
                    // Repeater at (lx, BY, lampZ) facing the lamp DIRECTLY
                    // Actually: dust at (lx, BY, lampZ) carries signal → repeater facing lamp
                    // But dust can't power lamp directly. Need repeater facing lamp.
                    // Lamp at (lx, BY, lampZ) — repeater at (lx, BY, lampZ) can't face it
                    // Need repeater at (lx+1, BY, lampZ) facing WEST into lamp, OR
                    // Need redstone block behind lamp
                    // Simplest: place redstone wire below lamp (BY) → powers lamp above? NO
                    // Redstone wire on the same Y as lamp doesn't power lamp unless it faces into it

                    // ACTUALLY: lamps are powered by adjacent POWERED BLOCKS.
                    // Place a STONE at (lx, BY, lampZ) with redstone_wire on top? No.
                    // The lamp is at (lx, BY, lampZ). To power it, I need:
                    // 1. A strongly powered block adjacent to it
                    // 2. Or a repeater facing into it
                    // Solution: repeater at (lx-1, BY, lampZ) facing EAST → lamp
                    bot.chat(`/setblock ${lx-1} ${BY} ${lampZ} minecraft:repeater[facing=east,delay=1]`);
                    // Wire from bus to this repeater
                    bot.chat(`/setblock ${lx-1} ${BY} ${z} minecraft:redstone_wire`);
                }
            }
        }
        await sleep(200);
    }

    // ========================================
    // Y=BY+1: Torches on latch stones
    // ========================================
    console.log('Y=BY+1: Latch torches...');
    for (let p=0; p<4; p++) {
        const z = BZ + p*4;
        bot.chat(`/setblock ${BX-4} ${BY+1} ${z} minecraft:redstone_torch[lit=true]`);
        bot.chat(`/setblock ${BX-2} ${BY+1} ${z} minecraft:redstone_torch[lit=true]`);
        await sleep(50);
    }

    // ========================================
    // NOTE_BLOCKS + OBSERVERS (Y=BY, at X=BX-8)
    // ========================================
    console.log('Y=BY: Note blocks + observers...');
    for (let p=0; p<4; p++) {
        const z = BZ + p*4;
        const nx = BX - 8;
        // Note block
        bot.chat(`/setblock ${nx} ${BY} ${z} minecraft:note_block`);
        // Observer at (nx+1, BY, z) facing WEST
        bot.chat(`/setblock ${nx+1} ${BY} ${z} minecraft:observer[facing=west]`);
        // Observer output at (nx+2, BY, z) → wire to latch

        // FAST RESET path: observer → direct wire to stone B (for ALL latches)
        bot.chat(`/setblock ${nx+2} ${BY} ${z} minecraft:redstone_wire`);
        for (let q=0; q<4; q++) {
            const qz = BZ + q*4;
            // Wire from observer output to all latch B stones
            for (let dx=nx+3; dx<BX-2; dx++)
                bot.chat(`/setblock ${dx} ${BY} ${qz} minecraft:redstone_wire`);
            // Repeater into stone B
            bot.chat(`/setblock ${BX-3} ${BY} ${qz} minecraft:repeater[facing=west,delay=1]`);
        }

        // DELAYED SET path: observer → 2 repeaters (delay 2rt) → stone A
        for (let yy=BY+1; yy<=BY+2; yy++)
            bot.chat(`/setblock ${nx+2} ${yy} ${z} minecraft:stone`);
        bot.chat(`/setblock ${nx+2} ${BY+3} ${z} minecraft:redstone_torch[lit=true]`);
        bot.chat(`/setblock ${nx+3} ${BY+3} ${z} minecraft:repeater[facing=east,delay=2]`);
        for (let dx=nx+4; dx<BX-4; dx++)
            bot.chat(`/setblock ${dx} ${BY+3} ${z} minecraft:redstone_wire`);
        bot.chat(`/setblock ${BX-5} ${BY+3} ${z} minecraft:repeater[facing=east,delay=1]`);
        // Down to stone A level
        bot.chat(`/setblock ${BX-4} ${BY+2} ${z} minecraft:repeater[facing=down,delay=1]`);
        await sleep(100);
    }

    // ========================================
    // CONFIRM: Q check lamps at latch outputs
    // ========================================
    console.log('Y=BY: Q check lamps...');
    for (let p=0; p<4; p++) {
        const z = BZ + p*4;
        bot.chat(`/setblock ${BX+W-1} ${BY} ${z} minecraft:redstone_lamp`);
    }
    await sleep(500);

    console.log(`\n✅ v5 Display built!`);
    console.log(`  Grid: ${BX},${BY},${BZ} — ${R}×${C}`);
    console.log(`  Latches: 4 RS NOR at Z=${BZ}+0/4/8/12`);
    console.log(`  Controls: Note blocks at X=${BX-8}`);
    console.log(`  Check: lamps at X=${BX+W-1} should toggle when note_blocks clicked`);
    bot.quit();
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 600000);
