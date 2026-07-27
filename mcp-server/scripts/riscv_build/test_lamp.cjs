// test_lamp.cjs — cleanest MC-31100 discriminator.
// redstone_block directly adjacent to a redstone_lamp. Lamp 'lit' state is
// server-authoritative (block state, not dust power cache).
//   place lamp, place block next to it -> lamp should light.
//   remove block -> lamp should go dark.
// If lamp NEVER changes with block presence, /setblock updates don't propagate.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_lamp', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const litAt = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return 'null'; const p = b.getProperties ? b.getProperties() : {}; return `${b.name}/lit=${p.lit}`; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const bx = Math.floor(p.x) + 8, by = Math.floor(p.y), bz = Math.floor(p.z) + 5;
  bot.chat(`/tp riscv_lamp ${bx} ${by} ${bz}`); await sleep(800);
  console.log(`[lamp] base ${bx},${by},${bz}`);

  bot.chat(`/setblock ${bx} ${by - 1} ${bz} minecraft:stone`); await sleep(200);
  bot.chat(`/setblock ${bx} ${by} ${bz} minecraft:redstone_lamp`); await sleep(300);
  bot.chat(`/setblock ${bx + 1} ${by} ${bz} minecraft:air`); await sleep(800);
  console.log(`[lamp] no power: ${litAt(bx, by, bz)}  (expect lit=false)`);

  bot.chat(`/setblock ${bx + 1} ${by} ${bz} minecraft:redstone_block`); await sleep(1200);
  const on = litAt(bx, by, bz);
  console.log(`[lamp] block adj: ${on}  (expect lit=true)`);

  bot.chat(`/setblock ${bx + 1} ${by} ${bz} minecraft:air`); await sleep(1200);
  const off = litAt(bx, by, bz);
  console.log(`[lamp] block gone: ${off}  (expect lit=false)`);

  const works = on.includes('lit=true');
  console.log(`[lamp] activation: ${works ? 'YES — updates propagate' : 'NO — inert (MC-31100 present, need mod)'}`);
  finish(works ? 0 : 42, works ? 'PASS' : 'FAIL_INERT');
});
setTimeout(() => finish(3, 'TIMEOUT'), 35000);
