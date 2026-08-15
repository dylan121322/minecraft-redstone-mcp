// build_alu1.cjs — in-game build of the pathfinder3d alu1 solution + 40-vector
// truth-table verification, via /setblock (one bot).
//
// Build area is 356 blocks wide — beyond one player's chunk radius (~13
// chunks). The bot /tp's itself along X in slices (~128 blocks each) during
// clear/floor/place phases. During TESTS the bot walks the slice between the
// PI edge (x0) and the output edge (x1) per vector; the client player should
// ALSO stand near the build centre to keep the whole chip ticked.
//
// Usage: node build_alu1.cjs <blocks.json> <host> <port> [originX originY originZ] [--tests tests.json]
const fs = require('fs');
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const args = process.argv.slice(2);
const blocksFile = args[0];
const HOST = args[1] || 'localhost';
const PORT = parseInt(args[2] || '6324', 10);
let ORIGIN = [0, 100, 200];
let testsFile = null;
let TEST_ONLY = false;
for (let i = 3; i < args.length; i++) {
  if (args[i] === '--tests') testsFile = args[++i];
  else if (args[i] === '--test-only') TEST_ONLY = true;
  else if (args[i] === '--origin') ORIGIN = [parseInt(args[++i]), parseInt(args[++i]), parseInt(args[++i])];
}

const data = JSON.parse(fs.readFileSync(blocksFile, 'utf8'));
const tests = testsFile ? JSON.parse(fs.readFileSync(testsFile, 'utf8')) : [];
const CMD_GAP = 150;     // ms between commands (multibot measured >150ms safe;
                        // 60ms dropped ~1% of 5.9k blocks -> broken nets in-game)
const SETTLE = 10000;     // ms redstone settle before each read (the
                        // chip has 30+ repeaters x 2 ticks = 60+ ticks; MCHPRS
                        // used 80 ticks = 4s — 1.5s read mid-transition)
const TIMEOUT = 2 * 3600 * 1000;
const SLICE = 128;       // x-teleport slice width (keeps everything < 8 chunks)

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'alu1_bld', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} for (const h of holders) { try { h.quit(); } catch {} } setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
bot.on('kicked', r => finish(1, `KICKED ${JSON.stringify(r)}`));
const C = s => bot.chat(s);
const abs = (p) => [ORIGIN[0] + p[0], ORIGIN[1] + p[1], ORIGIN[2] + p[2]];
const powerAt = (x, y, z) => {
  const b = bot.blockAt(new Vec3(x, y, z));
  if (!b) return -1;
  const p = b.getProperties ? b.getProperties() : {};
  if (p.power !== undefined) return Number(p.power);
  if (p.lit !== undefined) return p.lit ? 15 : 0;
  return 0;
};
async function setblock(x, y, z, s) { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(CMD_GAP); }
let botAbsX = null;
async function goto(x, y, z) {
  C(`/tp alu1_bld ${x} ${y} ${z}`);
  await sleep(1500);
  botAbsX = x;
}
async function nearX(wx) {
  if (botAbsX === null || Math.abs(wx - botAbsX) > SLICE) {
    await goto(wx, ORIGIN[1] + 4, ORIGIN[2] + 30);
  }
}

// HOLDER BOTS: keep the whole 356-block chip loaded during build+test. One
// bot's chunk radius (~10 chunks) is not enough; the client player is away.
// Holders teleport to the centre/east and idle. Chunks stay loaded because
// they are players too.
const holders = [];
async function spawnHolder(name, wx, wz) {
  const h = mineflayer.createBot({ host: HOST, port: PORT, username: name, auth: 'offline' });
  holders.push(h);
  await new Promise(res => { h.once('spawn', res); h.on('error', e => res()); });
  for (let tries = 0; tries < 4; tries++) {
    h.chat(`/tp ${name} ${wx} ${ORIGIN[1] + 4} ${wz}`);
    await sleep(1200);
    const pos = h.entity && h.entity.position;
    if (pos && Math.abs(pos.x - wx) <= 2 && Math.abs(pos.z - wz) <= 2) break;
    console.log(`  holder ${name} tp retry ${tries + 1} (at ${pos ? Math.round(pos.x) + ',' + Math.round(pos.z) : '?'})`);
  }
  console.log(`[alu1] holder ${name} at ${wx},${ORIGIN[1] + 4},${wz}`);
}
async function spawnHolders(ox, oz) {
  await spawnHolder('alu1_h1', ox + 177, oz + 30);
  await spawnHolder('alu1_h2', ox + 340, oz + 30);
}

bot.once('spawn', async () => {
  const [ox, oy, oz] = ORIGIN;
  const xs = data.blocks.map(b => b[0]), ys = data.blocks.map(b => b[1]), zs = data.blocks.map(b => b[2]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(...ys), y1 = Math.max(...ys);
  const z0 = Math.min(...zs), z1 = Math.max(...zs);
  console.log(`[alu1] ${data.name}: ${data.blocks.length} blocks, origin ${ox},${oy},${oz}, bbox x[${x0},${x1}] y[${y0},${y1}] z[${z0},${z1}]`);
  await spawnHolders(ox, oz);
  const p = bot.entity.position;
  console.log(`[alu1] bot spawn at ${Math.round(p.x)},${Math.round(p.y)},${Math.round(p.z)} (tp needs OP; if this is not near the origin the build may fail)`);

  if (TEST_ONLY) {
    console.log('[alu1] TEST-ONLY: skipping clear/floor/place');
  } else {
  // 1) clear the bbox in x-slices
  for (let sx = x0 - 2; sx <= x1 + 2; sx += SLICE) {
    const ex = Math.min(sx + SLICE - 1, x1 + 2);
    await nearX(ox + (sx + ex) / 2);
    for (let yy = y0 - 1; yy <= y1 + 2; yy++) {
      C(`/fill ${ox + sx} ${oy + yy} ${oz + z0 - 2} ${ox + ex} ${oy + yy} ${oz + z1 + 2} minecraft:air`);
      await sleep(CMD_GAP);
    }
  }
  await sleep(500);

  // 2) floor slab via /fill slices
  const floor = data.blocks.filter(b => b[1] === y0);
  if (floor.length > 0 && floor.every(b => b[3] === 'minecraft:stone')) {
    for (let sx = x0; sx <= x1; sx += SLICE) {
      const ex = Math.min(sx + SLICE - 1, x1);
      await nearX(ox + (sx + ex) / 2);
      C(`/fill ${ox + sx} ${oy + y0} ${oz + z0} ${ox + ex} ${oy + y0} ${oz + z1} minecraft:stone`);
      await sleep(CMD_GAP);
    }
    console.log(`[alu1] floor /fill: ${floor.length} blocks`);
  } else {
    console.log(`[alu1] no uniform floor (${floor.length}) — placing individually`);
  }

  // 3) rest: solids then redstone, x-sorted, teleporting along
  const piSet = new Set(Object.values(data.inputs).map(p => p.join(',')));
  const rest = data.blocks.filter(b => b[1] !== y0);
  const isRed = s => s.includes('redstone') || s.includes('repeater') || s.includes('torch');
  const solids = rest.filter(b => !isRed(b[3])).sort((a, b) => a[0] - b[0]);
  const reds = rest.filter(b => isRed(b[3])).sort((a, b) => a[0] - b[0]);
  let placed = 0;
  for (const [x, y, z, s] of solids) { const [ax, ay, az] = abs([x, y, z]); await nearX(ax); await setblock(ax, ay, az, s); placed++; }
  for (const [x, y, z, s] of reds) {
    if (piSet.has([x, y, z].join(','))) continue;
    const [ax, ay, az] = abs([x, y, z]); await nearX(ax); await setblock(ax, ay, az, s); placed++;
  }
  console.log(`[alu1] placed ${placed} blocks (${solids.length} solids + ${reds.length} reds)`);
  } // end TEST_ONLY skip
  await sleep(SETTLE);

  if (tests.length === 0) { finish(0, '[alu1] BUILD-ONLY DONE'); return; }

  // 4) truth table: drive PIs from the west edge, read outputs at the east edge
  let pass = 0;
  for (const tv of tests) {
    await nearX(ox + 8);
    for (const [name, pos] of Object.entries(data.inputs)) {
      const v = (tv.in[name] || 0);
      const [ax, ay, az] = abs(pos);
      await setblock(ax, ay, az, v ? 'minecraft:redstone_block' : 'minecraft:air');
    }
    await nearX(ox + x1 - 8);
    await sleep(SETTLE);
    const got = {};
    let ok = true;
    for (const [name, pos] of Object.entries(data.outputs)) {
      const [ax, ay, az] = abs(pos);
      const pw = powerAt(ax, ay, az);
      got[name] = pw > 0 ? 1 : 0;
      if (tv.out && tv.out[name] !== undefined && got[name] !== tv.out[name]) ok = false;
    }
    pass += ok ? 1 : 0;
    console.log(`  in=${JSON.stringify(tv.in)} exp=${JSON.stringify(tv.out)} got=${JSON.stringify(got)} ${ok ? 'OK' : 'X'}`);
  }
  console.log(`[alu1] ${pass}/${tests.length} ${pass === tests.length ? 'PASS' : 'FAIL'}`);
  finish(pass === tests.length ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, '[alu1] TIMEOUT'), TIMEOUT);
