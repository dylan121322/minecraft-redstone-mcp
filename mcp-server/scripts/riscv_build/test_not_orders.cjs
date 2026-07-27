// test_not_orders.cjs — find a build ORDER / input method that makes NOT work
// under MC-31100 (/setblock neighbor-update suppression).
// We test the NOT gate but vary how the powered state is established.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_ord', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; return p.lit; };

async function clearArea(bx, by, bz) {
  for (let dx = -1; dx <= 4; dx++) { C(`/setblock ${bx + dx} ${by} ${bz} minecraft:air`); C(`/setblock ${bx + dx} ${by - 1} ${bz} minecraft:stone`); }
  await sleep(400);
}

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const by = Math.floor(p.y);
  const ox = Math.floor(p.x) + 10, oz = Math.floor(p.z) + 10;
  C(`/tp riscv_ord ${ox} ${by} ${oz}`); await sleep(800);

  // ---- Test 1: place block FIRST, then mount, then torch (order fixes update) ----
  let bx = ox, bz = oz;
  await clearArea(bx, by, bz);
  C(`/setblock ${bx + 0} ${by} ${bz} minecraft:redstone_block`); await sleep(200); // input=1 FIRST
  C(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`); await sleep(200);          // mount
  C(`/setblock ${bx + 2} ${by} ${bz} minecraft:redstone_wall_torch[facing=east]`); await sleep(1200); // torch reads powered mount
  const o1 = lit(bx + 2, by, bz);
  console.log(`[T1 block-first, input=1] torch lit=${o1}  (want false)`);

  // ---- Test 2: use a BLOCK UPDATE poke — re-set the torch after block present ----
  bx = ox + 6; bz = oz;
  await clearArea(bx, by, bz);
  C(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`); await sleep(150);
  C(`/setblock ${bx + 2} ${by} ${bz} minecraft:redstone_wall_torch[facing=east]`); await sleep(300);
  C(`/setblock ${bx + 0} ${by} ${bz} minecraft:redstone_block`); await sleep(300);
  // poke: replace mount with itself to force a block update
  C(`/setblock ${bx + 1} ${by} ${bz} minecraft:air`); await sleep(150);
  C(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`); await sleep(1200);
  const o2 = lit(bx + 2, by, bz);
  console.log(`[T2 poke-mount, input=1] torch lit=${o2}  (want false)`);

  // ---- Test 3: LEVER as input on the mount (player-action update) ----
  bx = ox + 12; bz = oz;
  await clearArea(bx, by, bz);
  C(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`); await sleep(150);
  C(`/setblock ${bx + 2} ${by} ${bz} minecraft:redstone_wall_torch[facing=east]`); await sleep(300);
  // lever on top of mount, ON
  C(`/setblock ${bx + 1} ${by + 1} ${bz} minecraft:lever[face=floor,powered=true]`); await sleep(1400);
  const o3 = lit(bx + 2, by, bz);
  console.log(`[T3 lever-on-mount, input=1] torch lit=${o3}  (want false)`);

  console.log(`[RESULT] T1=${o1} T2=${o2} T3=${o3} — a 'false' means that method defeats MC-31100`);
  finish(0, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 55000);
