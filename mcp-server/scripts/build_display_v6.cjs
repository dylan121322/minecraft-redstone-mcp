/**
 * build_display_v6.cjs — Pure Redstone Display (All-Repeater Bus)
 *
 * KEY CONSTRAINT: All power paths use tight connections.
 *   Repeater reads from SOLID BLOCK (stone) next to it.
 *   Repeater outputs power to lamp directly in front.
 *   No gaps, no dust for power routing.
 *
 * Design:
 *   Bus: chain of repeaters at Y=BY
 *   Each lamp: repeater from bus facing EAST into lamp
 *   RS NOR: 2 stones + torches at each pattern position
 *   Q output → repeater bus → all lamps for pattern
 *
 * BUS layout (per pattern P, bus at Z = BZ + P*4):
 *   Row 0: repeater chain at (BX+1..BX+14, BY, busZ) facing EAST
 *   Actual: repeaters at (BX+1, BY, busZ), (BX+3, BY, busZ), ... spacing=2
 *   At each lamp position (BX+c*2, BY, BZ+r*2):
 *     IF pixel ON: repeater at (BX+c*2-1, BY, BZ+r*2) facing EAST → lamp
 *     This repeater reads from bus wire at (BX+c*2-1, BY, busZ)
 *     Bus wire connects via solid block path
 *
 * SIMPLIFIED: Each pattern has a set of REDSTONE BLOCKS placed at
 *   (lampX, BY, lampZ-1) for ON pixels. Note_block + observer + piston
 *   mechanism selects which pattern's blocks are active.
 *
 * EVEN SIMPLER: For now, just prove RS NOR + repeater works.
 *   Build 1 latch → repeater → 1 lamp. Verify. Then expand.
 */
const mineflayer = require('mineflayer');
const PORT = parseInt(process.env.PORT || '56804');
const bot = mineflayer.createBot({ host:'localhost', port:PORT, username:'V6Disp', keepalive:false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const X=-148, Y=59, Z=-25;

bot.once('spawn', async () => {
    console.log('v6: Single RS NOR → repeater → lamp');
    bot.chat(`/fill ${X-3} ${Y-2} ${Z-3} ${X+8} ${Y+3} ${Z+3} minecraft:air`);
    await sleep(500);
    // Stone floor
    bot.chat(`/fill ${X-3} ${Y-1} ${Z-3} ${X+8} ${Y-1} ${Z+3} minecraft:stone`);
    await sleep(500);

    // RS NOR: stones at (X, Y, Z) and (X+2, Y, Z)
    // Torches on top: (X, Y+1, Z) and (X+2, Y+1, Z)
    // Dust junction at (X+1, Y, Z)
    console.log('Building latch...');
    bot.chat(`/setblock ${X} ${Y} ${Z} minecraft:stone`);
    bot.chat(`/setblock ${X+2} ${Y} ${Z} minecraft:stone`);
    bot.chat(`/setblock ${X+1} ${Y} ${Z} minecraft:redstone_wire`);
    bot.chat(`/setblock ${X} ${Y+1} ${Z} minecraft:redstone_torch[lit=true]`);
    bot.chat(`/setblock ${X+2} ${Y+1} ${Z} minecraft:redstone_torch[lit=true]`);
    await sleep(300);

    // Q output: torch B at (X+2, Y+1, Z) → strongest power to stone below
    // Stone at (X+2, Y, Z) is strongly powered → repeater at (X+3, Y, Z) facing EAST reads this
    // BUT need tight connection: repeater input must be adjacent to powered stone
    bot.chat(`/setblock ${X+3} ${Y} ${Z} minecraft:repeater[facing=east,delay=1]`);
    // Repeater output goes to (X+4, Y, Z) → lamp
    bot.chat(`/setblock ${X+4} ${Y} ${Z} minecraft:redstone_lamp`);
    await sleep(1000);

    // Check initial state: Q should be 1 (torch B ON, repeater reads powered stone)
    bot.chat(`/execute if block ${X+4} ${Y} ${Z} minecraft:redstone_lamp[lit=true] run say V6_INIT`);
    await sleep(500);

    // SET: power stone A with redstone block
    bot.chat(`/setblock ${X-1} ${Y} ${Z} minecraft:redstone_block`);
    await sleep(2000);
    bot.chat(`/execute if block ${X+4} ${Y} ${Z} minecraft:redstone_lamp[lit=true] run say V6_SET`);
    // Remove SET
    bot.chat(`/setblock ${X-1} ${Y} ${Z} minecraft:air`);
    await sleep(2000);
    bot.chat(`/execute if block ${X+4} ${Y} ${Z} minecraft:redstone_lamp[lit=true] run say V6_HOLD`);
    await sleep(500);

    // RESET: power stone B
    bot.chat(`/setblock ${X+3} ${Y} ${Z-1} minecraft:redstone_block`);
    await sleep(2000);
    bot.chat(`/execute if block ${X+4} ${Y} ${Z} minecraft:redstone_lamp[lit=true] run say V6_RST`);
    await sleep(500);

    bot.quit();
});
bot.on('error', e => console.error(e.message));
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 30000);
