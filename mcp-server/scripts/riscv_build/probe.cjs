// probe.cjs — connect a bot to the target server, confirm /setblock works.
// Usage: node probe.cjs <host> <port>
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const USER = 'riscv_probe';

console.log(`[probe] connecting ${HOST}:${PORT} as ${USER}`);

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USER, auth: 'offline' });

let done = false;
const finish = (code, msg) => {
  if (done) return;
  done = true;
  if (msg) console.log(msg);
  try { bot.quit(); } catch {}
  setTimeout(() => process.exit(code), 300);
};

bot.on('error', (e) => finish(1, `[probe] ERROR ${e.code || ''} ${e.message}`));
bot.on('kicked', (r) => finish(1, `[probe] KICKED ${JSON.stringify(r)}`));
bot.on('end', (r) => { if (!done) finish(1, `[probe] END ${r}`); });

bot.once('spawn', async () => {
  const p = bot.entity.position;
  console.log(`[probe] SPAWNED at ${p.x.toFixed(1)},${p.y.toFixed(1)},${p.z.toFixed(1)}`);
  console.log(`[probe] gameMode=${bot.game.gameMode} dimension=${bot.game.dimension} version=${bot.version}`);

  // Try a /setblock at a probe location near spawn, then read it back.
  const bx = Math.floor(p.x) + 2, by = Math.floor(p.y), bz = Math.floor(p.z) + 2;
  console.log(`[probe] testing /setblock at ${bx},${by},${bz}`);
  bot.chat(`/setblock ${bx} ${by} ${bz} minecraft:stone`);

  setTimeout(() => {
    const blk = bot.blockAt(new Vec3(bx, by, bz));
    console.log(`[probe] blockAt = ${blk ? blk.name : 'null'}`);
    if (blk && blk.name === 'stone') {
      // clean up
      bot.chat(`/setblock ${bx} ${by} ${bz} minecraft:air`);
      finish(0, '[probe] SETBLOCK_OK — permissions confirmed');
    } else {
      finish(2, `[probe] SETBLOCK_FAILED — got ${blk ? blk.name : 'null'} (no cmd perms or chunk not loaded)`);
    }
  }, 1500);
});

setTimeout(() => finish(3, '[probe] TIMEOUT'), 45000);
