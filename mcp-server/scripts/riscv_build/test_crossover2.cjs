// test_crossover2.cjs — crossover using the PROVEN via primitive (repeater->block->dust-up).
// Net A: straight dust W->E at y=0 through x=cx.
// Net B: comes from south at y=0, uses repeater-via to climb to y=2, crosses
//        OVER A on a block bridge, descends via repeater-via back to y=0, to lamp.
// The bridge block for B sits at y=1 directly above A's dust — A stays at y=0,
// B's crossing dust at y=2. Vertical gap of 1 solid block => no coupling.
// Test all 4 input combos; PASS iff fully independent.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_xo2', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const G = 60;
const sb = async (x, y, z, s) => { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(G); };
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; if (p.lit !== undefined) return p.lit ? 1 : 0; if (p.power !== undefined) return Number(p.power) > 0 ? 1 : 0; return 0; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const oy = Math.floor(p.y);
  const ox = Math.floor(p.x) + 60, oz = Math.floor(p.z);
  C(`/tp riscv_xo2 ${ox} ${oy + 4} ${oz}`); await sleep(1200);
  const cx = ox + 4, cz = oz;      // crossing point
  console.log(`[xo2] crossing at ${cx},${oy},${cz}`);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 6} ${ox + 10} ${oy + 3} ${oz + 6} minecraft:air`); await sleep(400);
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 6} ${ox + 10} ${oy - 1} ${oz + 6} minecraft:stone`); await sleep(300);

  // --- Net A: dust straight through cx at y=0 ---
  for (let x = ox; x <= ox + 8; x++) await sb(x, oy, cz, 'minecraft:redstone_wire');
  await sb(ox + 9, oy, cz, 'minecraft:redstone_lamp');       // lampA east
  const injA = [ox - 1, oy, cz];

  // --- Net B: from south (cz-4) climb via repeater, bridge over A, descend ---
  // south run at y0
  await sb(cx, oy, cz - 4, 'minecraft:redstone_wire');
  await sb(cx, oy, cz - 3, 'minecraft:repeater[facing=north]'); // output north(+z toward crossing), input south
  await sb(cx, oy, cz - 2, 'minecraft:stone');                  // powered block
  await sb(cx, oy + 1, cz - 2, 'minecraft:redstone_wire');      // dust on top (y1)
  await sb(cx, oy + 1, cz - 1, 'minecraft:stone');              // rise
  await sb(cx, oy + 2, cz - 1, 'minecraft:redstone_wire');      // y2
  // bridge OVER A: block at y1 above A's dust (cx,oy,cz), crossing dust at y2
  await sb(cx, oy + 1, cz, 'minecraft:stone');                  // bridge support above A (A is at oy)
  await sb(cx, oy + 2, cz, 'minecraft:redstone_wire');          // B crosses at y2
  await sb(cx, oy + 1, cz + 1, 'minecraft:stone');
  await sb(cx, oy + 2, cz + 1, 'minecraft:redstone_wire');
  // descend via repeater on the far side
  await sb(cx, oy + 1, cz + 2, 'minecraft:stone');
  await sb(cx, oy + 2, cz + 2, 'minecraft:redstone_wire');      // still y2
  // step down: need to get from y2 back to y0. Use a downward staircase of dust
  // (descending dust DOES connect: dust at y2 connects to dust at y1 that is
  //  horizontally one step away sitting on a block — the "see below" rule).
  await sb(cx, oy, cz + 3, 'minecraft:stone');                  // block, top at oy+1
  await sb(cx, oy + 1, cz + 3, 'minecraft:redstone_wire');      // y1 dust (below+adjacent to y2 dust@cz+2)
  await sb(cx, oy, cz + 4, 'minecraft:redstone_wire');          // y0 dust
  await sb(cx, oy, cz + 5, 'minecraft:redstone_lamp');          // lampB
  const injB = [cx, oy, cz - 5];
  await sb(injB[0], injB[1], injB[2], 'minecraft:air'); // driver spot (south of B start)
  await sleep(400);

  let pass = 0;
  for (const [a, b] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
    await sb(injA[0], injA[1], injA[2], a ? 'minecraft:redstone_block' : 'minecraft:air');
    await sb(cx, oy, cz - 5, b ? 'minecraft:redstone_block' : 'minecraft:air'); // drive B start dust from south
    await sleep(1100);
    const la = lit(ox + 9, oy, cz), lb = lit(cx, oy, cz + 5);
    const ok = (la === a && lb === b);
    pass += ok ? 1 : 0;
    console.log(`   A=${a} B=${b} -> lampA=${la} lampB=${lb} ${ok ? 'OK' : 'X'}`);
  }
  console.log(`[xo2] repeater-via crossover: ${pass}/4 ${pass === 4 ? 'PASS — buildable crossover found' : 'FAIL'}`);
  finish(pass === 4 ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 180000);
