// test_dynamic.cjs — can the SAME built NOT gate be re-driven with changing input?
// Build once (dust->mount->wall_torch). Then toggle the far-end driver
// block on/off several times, reading torch lit each time. This is exactly
// how we'll run test vectors: build gate once, change PI blocks, re-read.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_dyn', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; return p.lit; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const by = Math.floor(p.y);
  const ox = Math.floor(p.x) + 25, oz = Math.floor(p.z) + 25;
  C(`/tp riscv_dyn ${ox} ${by} ${oz}`); await sleep(800);
  console.log(`[dyn] base ${ox},${by},${oz}`);
  for (let dx = -1; dx <= 6; dx++) { C(`/setblock ${ox + dx} ${by} ${oz} minecraft:air`); C(`/setblock ${ox + dx} ${by - 1} ${oz} minecraft:stone`); }
  await sleep(500);

  // build NOT: driver@0, wire@1, wire@2, mount@3, wall_torch(east)@4, out wire@5
  C(`/setblock ${ox + 1} ${by} ${oz} minecraft:redstone_wire`); await sleep(120);
  C(`/setblock ${ox + 2} ${by} ${oz} minecraft:redstone_wire`); await sleep(120);
  C(`/setblock ${ox + 3} ${by} ${oz} minecraft:stone`); await sleep(120);
  C(`/setblock ${ox + 4} ${by} ${oz} minecraft:redstone_wall_torch[facing=east]`); await sleep(120);
  C(`/setblock ${ox + 5} ${by} ${oz} minecraft:redstone_wire`); await sleep(400);

  const seq = [1, 0, 1, 0, 1];  // input values to apply
  const results = [];
  for (const v of seq) {
    C(`/setblock ${ox + 0} ${by} ${oz} ${v ? 'minecraft:redstone_block' : 'minecraft:air'}`);
    await sleep(1100);
    const t = lit(ox + 4, by, oz);
    const expect = v ? false : true;  // NOT: torch lit = !input
    const ok = (t === expect);
    results.push(ok);
    console.log(`  input=${v} torch_lit=${t} expect=${expect} ${ok ? 'OK' : 'X'}`);
  }
  const allOk = results.every(Boolean);
  console.log(`[dyn] dynamic re-drive: ${allOk ? 'YES — gate toggles correctly, test vectors viable' : 'NO — stuck state'}`);
  finish(allOk ? 0 : 42, allOk ? 'PASS' : 'FAIL');
});
setTimeout(() => finish(3, 'TIMEOUT'), 45000);
