// test_climb.cjs — how does a signal change Y-layer under /setblock (no updates)?
// Test several vertical-transition primitives, each driven and read via lamp:
//
//  C1 dust staircase: dust climbs adjacent stair blocks (classic). y0->y2.
//  C2 repeater ramp: repeater into a block, dust on top (repeaters force update).
//  C3 vertical torch ladder: torch on side of block stacks (NOR-style riser).
//  C4 dust straight up a 1-wide column of blocks (dust on each block face) - not valid in vanilla.
//
// We want ONE primitive that reliably moves a signal from y=0 to y=2 and back
// with /setblock. That primitive becomes the router's "via".
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_climb', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const G = 60;
const sb = async (x, y, z, s) => { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(G); };
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; if (p.lit !== undefined) return p.lit ? 1 : 0; if (p.power !== undefined) return Number(p.power) > 0 ? 1 : 0; return 0; };

// drive a net by toggling redstone_block at inj, read lamp; return [off,on] results
async function probe(inj, lamp) {
  const res = [];
  for (const v of [0, 1]) {
    await sb(inj[0], inj[1], inj[2], v ? 'minecraft:redstone_block' : 'minecraft:air');
    await sleep(1000);
    res.push(lit(...lamp));
  }
  await sb(inj[0], inj[1], inj[2], 'minecraft:air');
  return res; // want [0,1]
}

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const oy = Math.floor(p.y);
  const ox = Math.floor(p.x) - 40, oz = Math.floor(p.z) + 40;
  C(`/tp riscv_climb ${ox} ${oy + 4} ${oz}`); await sleep(1200);
  console.log(`[climb] base ${ox},${oy},${oz}`);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 2} ${ox + 30} ${oy + 4} ${oz + 8} minecraft:air`); await sleep(500);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 2} ${ox + 30} ${oy - 1} ${oz + 8} minecraft:stone`); await sleep(400);

  // ---- C1: dust staircase y0 -> y2 -> y0, straight along +x ----
  // inj@(ox-1) drives dust@ox(y0); stair up; top dust; stair down; lamp
  let x = ox;
  await sb(x, oy, oz, 'minecraft:redstone_wire');             // y0
  await sb(x + 1, oy, oz, 'minecraft:stone');                  // step
  await sb(x + 1, oy + 1, oz, 'minecraft:redstone_wire');     // on step (y1)
  await sb(x + 2, oy + 1, oz, 'minecraft:stone');             // step2
  await sb(x + 2, oy + 2, oz, 'minecraft:redstone_wire');     // y2 top
  await sb(x + 3, oy + 1, oz, 'minecraft:stone');             // down-step (dust above it sees y2 dust)
  await sb(x + 3, oy + 2, oz, 'minecraft:redstone_wire');     // y2
  await sb(x + 4, oy + 1, oz, 'minecraft:redstone_wire');     // step down to y1 (rests on floor? no, on nothing) -> need block
  await sb(x + 4, oy, oz, 'minecraft:stone');                 // support for the y1 dust above? actually put dust on ground
  await sb(x + 5, oy, oz, 'minecraft:redstone_lamp');
  const c1 = await probe([ox - 1, oy, oz], [x + 5, oy, oz]);
  console.log(`[C1 dust staircase] ${JSON.stringify(c1)} want [0,1] ${c1[0] === 0 && c1[1] === 1 ? 'PASS' : 'FAIL'}`);

  // ---- C2: repeater-forced layer change. dust->repeater->block, dust on top ----
  const z2 = oz + 4; x = ox;
  await sb(x, oy, z2, 'minecraft:redstone_wire');
  await sb(x + 1, oy, z2, 'minecraft:repeater[facing=west]');  // input from west(dust), output east
  await sb(x + 2, oy, z2, 'minecraft:stone');                  // repeater strongly powers this block
  await sb(x + 2, oy + 1, z2, 'minecraft:redstone_wire');      // dust on top of powered block -> lit
  await sb(x + 3, oy + 1, z2, 'minecraft:stone');
  await sb(x + 3, oy + 2, z2, 'minecraft:redstone_wire');      // climb higher
  await sb(x + 4, oy + 2, z2, 'minecraft:redstone_lamp');
  const c2 = await probe([ox - 1, oy, z2], [x + 4, oy + 2, z2]);
  console.log(`[C2 repeater->block->dust-up] ${JSON.stringify(c2)} want [0,1] ${c2[0] === 0 && c2[1] === 1 ? 'PASS' : 'FAIL'}`);

  finish(0, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 90000);
