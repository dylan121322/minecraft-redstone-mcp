/**
 * build_display_8x8.cjs — 8×8 Lamp Matrix (Phase 1: Grid Only)
 *
 * Places 64 lamps in an 8×8 grid on a glass base.
 * Pattern setting: use /setblock to toggle individual lamps.
 * Later phases will add row/col decoders and ROM.
 */
const mineflayer = require('mineflayer');

const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host: 'localhost', port: PORT, username: 'Disp8x8', keepalive: false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const ROWS = 8, COLS = 8, GAP = 2;

bot.once('spawn', async () => {
    const p = bot.entity.position;
    const OX = Math.round(p.x) + 5;
    const OY = Math.round(p.y) + 1;
    const OZ = Math.round(p.z);
    console.log(`Building 8×8 display at ${OX},${OY},${OZ}`);

    const W = (COLS-1) * GAP + 3;
    const D = (ROWS-1) * GAP + 3;

    // Clear + glass base
    bot.chat(`/fill ${OX-2} ${OY-1} ${OZ-2} ${OX+W} ${OY+1} ${OZ+D} minecraft:air`);
    await sleep(1000);
    bot.chat(`/fill ${OX-2} ${OY-1} ${OZ-2} ${OX+W} ${OY-1} ${OZ+D} minecraft:glass`);
    await sleep(1000);

    // Place lamps
    console.log(`Placing ${ROWS*COLS} lamps...`);
    let count = 0;
    for (let row = 0; row < ROWS; row++) {
        for (let col = 0; col < COLS; col++) {
            bot.chat(`/setblock ${OX+col*GAP} ${OY} ${OZ+row*GAP} minecraft:redstone_lamp`);
            count++;
            if (count % 16 === 0) {
                console.log(`  ${count}/${ROWS*COLS}`);
                await sleep(100);
            }
            if (count % 3 === 0) await sleep(50);
        }
    }
    await sleep(500);

    // Row labels (stone pillars with signs)
    for (let row = 0; row < ROWS; row++) {
        bot.chat(`/setblock ${OX-2} ${OY} ${OZ+row*GAP} minecraft:stone`);
    }
    await sleep(300);

    console.log(`\n8×8 Grid built:`);
    console.log(`  Lamps: ${ROWS*COLS} at (${OX},${OY},${OZ}) to (${OX+14},${OY},${OZ+14})`);
    console.log(`  To test: use /setblock <x> <y> <z> minecraft:redstone_lamp[lit=true]`);
    bot.quit();
});

bot.on('error', e => { if (!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 60000);
