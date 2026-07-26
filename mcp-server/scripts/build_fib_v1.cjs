/**
 * build_fib_v1.cjs — Fibonacci Computer builder (HashDG fib_computer.schem)
 * ALL /setblock, requires redstone-update-fix mod.
 * Usage: PORT=xxxxx node build_fib_v1.cjs
 */
const mineflayer = require('mineflayer');
const { execSync } = require('child_process');

const PORT = parseInt(process.env.PORT || '25565');
const bot = mineflayer.createBot({ host: 'localhost', port: PORT, username: 'FibBuilder', keepalive: false });
const sleep = ms => new Promise(r => setTimeout(r, ms));

bot.once('spawn', async () => {
    console.log('Loading fib_computer.schem...');
    const data = JSON.parse(execSync(
        'python3 -c "import nucleation as nuc, json; schem=nuc.Schematic.open(\'<SCHEMATIC_PATH>\'); b=json.loads(schem.bounding_box_json()) if isinstance(schem.bounding_box_json(),str) else list(schem.bounding_box_json()); blocks=[]; [blocks.append([x,y,z,schem.get_block_string(x,y,z)]) for x in range(b[0],b[3]+1) for y in range(b[1],b[4]+1) for z in range(b[2],b[5]+1) if schem.get_block_string(x,y,z) and \'air\' not in schem.get_block_string(x,y,z)]; print(json.dumps({\'bounds\':b,\'blocks\':blocks}))"',
        { maxBuffer: 10 * 1024 * 1024 }
    ).toString().trim().split('\n').pop());
    const { bounds, blocks } = data;
    console.log(`Bounds: ${bounds}, Total: ${blocks.length}`);

    const pos = bot.entity.position;
    const DX = Math.round(pos.x) + 5;
    const GY = Math.round(pos.y) + 2;
    const DZ = Math.round(pos.z);
    console.log(`Building at ${DX},${GY},${DZ}`);

    // Glass base + clear
    bot.chat(`/fill ${DX-3} ${GY-1} ${DZ-3} ${DX+18} ${GY+16} ${DZ+22} minecraft:air`);
    await sleep(1500);
    bot.chat(`/fill ${DX-3} ${GY-1} ${DZ-3} ${DX+18} ${GY-1} ${DZ+22} minecraft:glass`);
    await sleep(1500);

    // Place all blocks sorted by Y
    const sorted = [...blocks].sort((a, b) => a[1] - b[1]);
    console.log(`Placing ${sorted.length} blocks...`);
    const start = Date.now();
    for (let i = 0; i < sorted.length; i++) {
        const [x, y, z, block] = sorted[i];
        bot.chat(`/setblock ${DX+x} ${GY+y} ${DZ+z} ${block}`);
        if (i % 200 === 0) {
            const e = ((Date.now() - start) / 1000).toFixed(1);
            process.stdout.write(`\r  ${i}/${sorted.length} (${e}s)`);
            await sleep(30);
        }
        if (i % 5 === 0) await sleep(200);
    }
    const elapsed = ((Date.now() - start) / 1000).toFixed(1);
    console.log(`\r  ${sorted.length}/${sorted.length} done in ${elapsed}s`);

    console.log(`\nFib Computer at ${DX},${GY},${DZ}`);
    console.log('Controls: note_block at (DX+4,DZ+3), (DX+6,DZ+3), (DX+8,DZ+3)');
    console.log('Output: lamps at X=DX+1, DX+5, Z varies, Y=3..11');
    bot.quit();
});

bot.on('error', e => { if (!e.message.includes('ECONNRESET')) console.error('Err:', e.message); });
bot.on('end', () => process.exit(0));
setTimeout(() => process.exit(1), 300000);
