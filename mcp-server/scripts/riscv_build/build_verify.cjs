// build_verify.cjs — build a exported .blocks.json in-game, then drive test
// vectors by toggling PI redstone_blocks and reading outputs. Reports pass/fail.
//
// Usage: node build_verify.cjs <blocks.json> <host> <port> [originX originY originZ]
//        node build_verify.cjs <blocks.json> ... --tests tests.json
//
// tests.json: [{ "in": {"A":1,"B":0}, "out": {"Q":0} }, ...]
// If no tests file: for a single-output combinational cell we auto-generate the
// full truth table only when a --truth <expr> is given; otherwise we just build.
const fs = require('fs');
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const args = process.argv.slice(2);
const blocksFile = args[0];
const HOST = args[1] || 'frp-tag.com';
const PORT = parseInt(args[2] || '40269', 10);
let ORIGIN = [0, 60, 0];
let testsFile = null;
for (let i = 3; i < args.length; i++) {
  if (args[i] === '--tests') testsFile = args[++i];
  else if (args[i] === '--origin') ORIGIN = [parseInt(args[++i]), parseInt(args[++i]), parseInt(args[++i])];
}

const data = JSON.parse(fs.readFileSync(blocksFile, 'utf8'));
const tests = testsFile ? JSON.parse(fs.readFileSync(testsFile, 'utf8')) : [];
const CMD_GAP = 60;   // ms between /setblock (well under the 150ms drop threshold)
const SETTLE = 900;   // ms to let redstone settle before reading

const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_bld', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
bot.on('kicked', r => finish(1, `KICKED ${JSON.stringify(r)}`));
const C = s => bot.chat(s);
const abs = (p) => [ORIGIN[0] + p[0], ORIGIN[1] + p[1], ORIGIN[2] + p[2]];
const powerAt = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return -1; const p = b.getProperties ? b.getProperties() : {}; if (p.power !== undefined) return Number(p.power); if (p.lit !== undefined) return p.lit ? 15 : 0; return 0; };

async function setblock(x, y, z, s) { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(CMD_GAP); }

bot.once('spawn', async () => {
  const [ox, oy, oz] = ORIGIN;
  console.log(`[bld] ${data.name}: ${data.blocks.length} blocks, origin ${ox},${oy},${oz}, kind=${data.kind}`);
  C(`/tp riscv_bld ${ox} ${oy + 3} ${oz}`); await sleep(1000);

  // 1) clear a generous bbox first (avoid old debris)
  const xs = data.blocks.map(b => b[0]), ys = data.blocks.map(b => b[1]), zs = data.blocks.map(b => b[2]);
  const x0 = Math.min(...xs) - 2, x1 = Math.max(...xs) + 2;
  const y0 = Math.min(...ys) - 1, y1 = Math.max(...ys) + 2;
  const z0 = Math.min(...zs) - 2, z1 = Math.max(...zs) + 2;
  console.log(`[bld] clearing bbox x[${x0},${x1}] y[${y0},${y1}] z[${z0},${z1}]`);
  // use /fill in chunks (fill is one command, fast)
  for (let yy = y0; yy <= y1; yy++) {
    C(`/fill ${ox + x0} ${oy + yy} ${oz + z0} ${ox + x1} ${oy + yy} ${oz + z1} minecraft:air`);
    await sleep(CMD_GAP);
  }
  await sleep(500);

  // 2) place all non-PI blocks. Skip PI injector positions (we drive those).
  const piSet = new Set(Object.values(data.inputs).map(p => p.join(',')));
  let placed = 0;
  // place floor/stone first, then wires/components (order: solids then redstone)
  const solids = data.blocks.filter(b => !b[3].includes('redstone') && !b[3].includes('repeater') && !b[3].includes('torch'));
  const reds = data.blocks.filter(b => b[3].includes('redstone') || b[3].includes('repeater') || b[3].includes('torch'));
  for (const [x, y, z, s] of solids) { const [ax, ay, az] = abs([x, y, z]); await setblock(ax, ay, az, s); placed++; }
  for (const [x, y, z, s] of reds) {
    if (piSet.has([x, y, z].join(','))) continue; // don't place a block where PI injects
    const [ax, ay, az] = abs([x, y, z]); await setblock(ax, ay, az, s); placed++;
  }
  console.log(`[bld] placed ${placed} blocks (${solids.length} solids + reds)`);
  await sleep(SETTLE);

  if (tests.length === 0) { finish(0, '[bld] BUILD-ONLY (no tests) DONE'); return; }

  // 3) run test vectors
  let pass = 0;
  for (const tv of tests) {
    // set every PI: redstone_block for 1, air for 0
    for (const [name, pos] of Object.entries(data.inputs)) {
      const v = (tv.in[name] || 0);
      const [ax, ay, az] = abs(pos);
      await setblock(ax, ay, az, v ? 'minecraft:redstone_block' : 'minecraft:air');
    }
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
  console.log(`[bld] ${data.name}: ${pass}/${tests.length} ${pass === tests.length ? 'PASS' : 'FAIL'}`);
  finish(pass === tests.length ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, '[bld] TIMEOUT'), 300000);
