// test_torch_direct.cjs — pin down exactly what propagates under /setblock here.
// Four micro-tests, each reading server-authoritative 'lit':
//  A) standing redstone_torch placed ON a redstone_block -> must be lit=false (torch burns out)
//  B) same but torch placed FIRST, then block under it
//  C) re-set (poke) the torch itself after block is under it
//  D) does a repeater carry? redstone_block -> repeater -> lamp
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_dir', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const prop = (x, y, z, k) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; return { name: b.name, v: p[k] }; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const by = Math.floor(p.y);
  const ox = Math.floor(p.x) - 15, oz = Math.floor(p.z) + 15;
  C(`/tp riscv_dir ${ox} ${by} ${oz}`); await sleep(800);
  console.log(`[dir] base ${ox},${by},${oz}`);

  // clear a strip
  for (let dx = 0; dx <= 20; dx++) for (let dz = 0; dz <= 4; dz++) { C(`/setblock ${ox + dx} ${by} ${oz + dz} minecraft:air`); C(`/setblock ${ox + dx} ${by - 1} ${oz + dz} minecraft:air`); }
  await sleep(600);

  // A) block THEN torch on top
  C(`/setblock ${ox} ${by} ${oz} minecraft:redstone_block`); await sleep(200);
  C(`/setblock ${ox} ${by + 1} ${oz} minecraft:redstone_torch`); await sleep(1200);
  const A = prop(ox, by + 1, oz, 'lit');
  console.log(`[A block-then-torch-on-top] ${JSON.stringify(A)} (want lit=false)`);

  // B) torch THEN block under
  C(`/setblock ${ox + 3} ${by + 1} ${oz} minecraft:redstone_torch`); await sleep(300);
  C(`/setblock ${ox + 3} ${by} ${oz} minecraft:redstone_block`); await sleep(1200);
  const B = prop(ox + 3, by + 1, oz, 'lit');
  console.log(`[B torch-then-block-under] ${JSON.stringify(B)} (want lit=false)`);

  // C) poke torch: re-place it after block under
  C(`/setblock ${ox + 6} ${by} ${oz} minecraft:redstone_block`); await sleep(200);
  C(`/setblock ${ox + 6} ${by + 1} ${oz} minecraft:redstone_torch`); await sleep(200);
  C(`/setblock ${ox + 6} ${by + 1} ${oz} minecraft:air`); await sleep(150);
  C(`/setblock ${ox + 6} ${by + 1} ${oz} minecraft:redstone_torch`); await sleep(1200);
  const Cc = prop(ox + 6, by + 1, oz, 'lit');
  console.log(`[C poke-torch] ${JSON.stringify(Cc)} (want lit=false)`);

  // D) repeater carry: block -> repeater(east) -> lamp
  C(`/setblock ${ox + 9} ${by - 1} ${oz} minecraft:stone`); await sleep(100);
  C(`/setblock ${ox + 10} ${by - 1} ${oz} minecraft:stone`); await sleep(100);
  C(`/setblock ${ox + 11} ${by - 1} ${oz} minecraft:stone`); await sleep(100);
  C(`/setblock ${ox + 9} ${by} ${oz} minecraft:redstone_block`); await sleep(200);
  C(`/setblock ${ox + 10} ${by} ${oz} minecraft:repeater[facing=west]`); await sleep(200); // input from west (block side)
  C(`/setblock ${ox + 11} ${by} ${oz} minecraft:redstone_lamp`); await sleep(1400);
  const D = prop(ox + 11, by, oz, 'lit');
  console.log(`[D block->repeater->lamp] ${JSON.stringify(D)} (want lit=true)`);

  finish(0, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 55000);
