/**
 * build_display_v2.cjs — Clean 8×8 Lamp Grid
 * Frame switching via bot script (HW ROM later)
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'DispV2', keepalive:false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const OX = 10, OY = 59, OZ = 5, GAP = 2, COLS = 8, ROWS = 8;
const W = (COLS-1)*GAP+2, D = (ROWS-1)*GAP+2;

bot.once('spawn', async () => {
    console.log(`Building 8×8 Grid at ${OX},${OY},${OZ}`);

    // Clear
    bot.chat(`/fill ${OX-3} ${OY-1} ${OZ-3} ${OX+W} ${OY+1} ${OZ+D} minecraft:air`);
    await sleep(1000);
    bot.chat(`/fill ${OX-3} ${OY-1} ${OZ-3} ${OX+W} ${OY-1} ${OZ+D} minecraft:glass`);
    await sleep(1000);

    // Lamps
    console.log(`Placing 64 lamps...`);
    for (let r=0; r<ROWS; r++) {
        for (let c=0; c<COLS; c++) {
            bot.chat(`/setblock ${OX+c*GAP} ${OY} ${OZ+r*GAP} minecraft:redstone_lamp`);
        }
        await sleep(30);
    }
    await sleep(500);

    // Border markers (stone + signs for row/col labels)
    for (let r=0; r<ROWS; r++) {
        bot.chat(`/setblock ${OX-2} ${OY} ${OZ+r*GAP} minecraft:stone`);
    }
    for (let c=0; c<COLS; c++) {
        bot.chat(`/setblock ${OX+c*GAP} ${OY} ${OZ-2} minecraft:stone`);
    }
    await sleep(300);

    console.log(`\nGrid built:`);
    console.log(`  ${ROWS}×${COLS} = ${ROWS*COLS} lamps`);
    console.log(`  Area: ${OX},${OY},${OZ} → ${OX+(COLS-1)*GAP},${OY},${OZ+(ROWS-1)*GAP}`);
    console.log(`  Power: redstone_block at lamp's Z-1 position turns it on`);
    bot.quit();
});

bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 30000);
