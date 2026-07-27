// cleanup.cjs — clear all probe/test debris around spawn so module builds start clean.
const mineflayer = require('mineflayer');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_clean', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const cx = Math.floor(p.x), cy = Math.floor(p.y), cz = Math.floor(p.z);
  console.log(`[clean] spawn ${cx},${cy},${cz}`);
  // clear a big volume around spawn covering all probe areas (they were within ~±60)
  // fill in 32-wide chunks to respect command limits; teleport along the way
  for (let x = cx - 70; x <= cx + 110; x += 30) {
    C(`/tp riscv_clean ${x} ${cy + 5} ${cz}`); await sleep(700);
    for (let dy = -2; dy <= 6; dy++) {
      C(`/fill ${x} ${cy + dy} ${cz - 70} ${x + 29} ${cy + dy} ${cz + 70} minecraft:air`);
      await sleep(80);
    }
  }
  console.log('[clean] done');
  finish(0, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 120000);
