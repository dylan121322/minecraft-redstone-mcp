// test_not.cjs — NOT gate correctness via TORCH lit state (server-authoritative).
// mount(stone) at dx=1; wall_torch(east) at dx=2 attached to mount's east face...
// Actually: torch facing=east is mounted on the block to its WEST (dx=1 mount).
// Input redstone_block at dx=0 powers mount(dx=1) -> torch(dx=2) turns OFF.
// Remove block -> mount unpowered -> torch ON.
// Read torch 'lit' both cases: lit must equal NOT(input).
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_not', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; return { name: b.name, lit: p.lit }; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const bx = Math.floor(p.x) + 8, by = Math.floor(p.y), bz = Math.floor(p.z) - 5;
  bot.chat(`/tp riscv_not ${bx} ${by} ${bz}`); await sleep(800);
  console.log(`[not] base ${bx},${by},${bz}`);

  // floor + clear
  for (let dx = -1; dx <= 4; dx++) { bot.chat(`/setblock ${bx + dx} ${by - 1} ${bz} minecraft:stone`); }
  await sleep(300);
  for (let dx = -1; dx <= 4; dx++) { bot.chat(`/setblock ${bx + dx} ${by} ${bz} minecraft:air`); }
  await sleep(400);

  bot.chat(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`); await sleep(250);          // mount
  bot.chat(`/setblock ${bx + 2} ${by} ${bz} minecraft:redstone_wall_torch[facing=east]`); await sleep(400); // torch on east face of mount

  // input=0
  bot.chat(`/setblock ${bx + 0} ${by} ${bz} minecraft:air`); await sleep(1200);
  const t0 = lit(bx + 2, by, bz);
  console.log(`[not] input=0: torch ${JSON.stringify(t0)}  (expect lit=true)`);

  // input=1 : redstone_block powers mount
  bot.chat(`/setblock ${bx + 0} ${by} ${bz} minecraft:redstone_block`); await sleep(1400);
  const t1 = lit(bx + 2, by, bz);
  console.log(`[not] input=1: torch ${JSON.stringify(t1)}  (expect lit=false)`);

  const ok = t0 && t1 && t0.lit === true && t1.lit === false;
  console.log(`[not] NOT via torch-lit: ${ok ? 'YES — gate works, build viable' : 'NO'}`);
  finish(ok ? 0 : 42, ok ? 'PASS' : 'FAIL');
});
setTimeout(() => finish(3, 'TIMEOUT'), 40000);
