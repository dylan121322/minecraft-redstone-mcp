// test_via.cjs — settle the bridge via gadget: y0 -> y2 climb -> y2 run -> y0 descend.
// Build the EXACT gadget the router will emit, drive it, read the far lamp.
// Two climb styles at the up-end:
//   VU "repeater-via": dust -> repeater -> block+dust(y1) -> block+dust(y2)
//   descent: dust(y2) -> block+dust(y1) -> dust(y0) -> lamp
// This is the standalone "wire that goes up and over and comes back down".
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_via', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const G = 70;
const sb = async (x, y, z, s) => { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(G); };
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; if (p.lit !== undefined) return p.lit ? 1 : 0; if (p.power !== undefined) return Number(p.power) > 0 ? 1 : 0; return 0; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const oy = Math.floor(p.y);
  const ox = Math.floor(p.x) - 60, oz = Math.floor(p.z) - 60;
  C(`/tp riscv_via ${ox} ${oy + 4} ${oz}`); await sleep(1200);
  console.log(`[via] base ${ox},${oy},${oz}`);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 2} ${ox + 14} ${oy + 4} ${oz + 4} minecraft:air`); await sleep(400);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 2} ${ox + 14} ${oy - 1} ${oz + 4} minecraft:stone`); await sleep(300);

  // Gadget travels in +x. flow +x -> repeater facing=west (reverse of flow).
  const z = oz;
  let x = ox;
  await sb(x, oy, z, 'minecraft:redstone_wire');                 // y0 start (driven from west)
  x += 1;
  await sb(x, oy, z, 'minecraft:repeater[facing=west]');          // repeater, output +x (east)
  x += 1;
  await sb(x, oy, z, 'minecraft:stone');                          // block strong-powered by repeater
  await sb(x, oy + 1, z, 'minecraft:redstone_wire');             // dust on top (y1)
  x += 1;
  await sb(x, oy + 1, z, 'minecraft:stone');                      // rise block (y1)
  await sb(x, oy + 2, z, 'minecraft:redstone_wire');             // y2 dust (climb complete)
  // y2 run a few tiles
  x += 1; await sb(x, oy + 1, z, 'minecraft:stone'); await sb(x, oy + 2, z, 'minecraft:redstone_wire');
  x += 1; await sb(x, oy + 1, z, 'minecraft:stone'); await sb(x, oy + 2, z, 'minecraft:redstone_wire');
  // descend: y2 dust -> block+dust(y1) -> dust(y0) -> lamp
  x += 1; await sb(x, oy, z, 'minecraft:stone'); await sb(x, oy + 1, z, 'minecraft:redstone_wire'); // y1 dust on block (top oy+1)
  x += 1; await sb(x, oy, z, 'minecraft:redstone_wire');         // y0 dust
  x += 1; await sb(x, oy, z, 'minecraft:redstone_lamp');         // lamp
  const lampX = x;
  await sleep(400);

  const res = [];
  for (const v of [0, 1, 0, 1]) {
    await sb(ox - 1, oy, z, v ? 'minecraft:redstone_block' : 'minecraft:air');
    await sleep(1100);
    const l = lit(lampX, oy, z);
    res.push(l === v);
    console.log(`   drive=${v} lamp=${l} ${l === v ? 'OK' : 'X'}`);
  }
  const ok = res.every(Boolean);
  console.log(`[via] up-over-down gadget: ${ok ? 'PASS — bridge via conducts dynamically' : 'FAIL'}`);
  finish(ok ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 90000);
