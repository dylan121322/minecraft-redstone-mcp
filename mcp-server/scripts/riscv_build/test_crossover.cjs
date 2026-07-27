// test_crossover.cjs — can two independent redstone nets CROSS without shorting,
// built purely with /setblock (no block updates) on this vanilla server?
// This primitive is the foundation of any correct router. Test 2 variants:
//
//  Net A: west->east along z=0, y=0  (driverA at west, lampA at east)
//  Net B: south->north crossing A. Must stay independent.
//
// VARIANT 1 "up-and-over" (dust climb): B climbs to y=2 over A via block stairs.
// VARIANT 2 "block bridge": B rides on solid blocks at y=2, A passes under.
//
// Independence test: toggle A and B through all 4 combos, read both lamps.
// PASS iff lampA==A and lampB==B for all 4 combos (no cross-coupling).
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_xover', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const G = 60;
const sb = async (x, y, z, s) => { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(G); };
const litP = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; if (p.lit !== undefined) return p.lit ? 1 : 0; if (p.power !== undefined) return Number(p.power) > 0 ? 1 : 0; return 0; };

async function buildVariant1(ox, oy, oz) {
  // clear
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 4} ${ox + 8} ${oy + 3} ${oz + 4} minecraft:air`); await sleep(400);
  // floor slab
  C(`/fill ${ox - 2} ${oy - 1} ${oz - 4} ${ox + 8} ${oy - 1} ${oz + 4} minecraft:stone`); await sleep(300);

  // Net A: straight dust west->east along z=0 at y=0, crossing point x=ox+3
  // driverA @ (ox, oy, oz) ; dust ox+1..ox+5 ; lampA @ ox+6
  for (let x = ox + 1; x <= ox + 5; x++) await sb(x, oy, oz, 'minecraft:redstone_wire');
  await sb(ox + 6, oy, oz, 'minecraft:redstone_lamp');

  // Net B: from oz-3 to oz+3 along x=ox+3, going UP and OVER A.
  // B south side: dust at (ox+3, oy, oz-3),(oz-2)
  // climb: block@(ox+3,oy,oz-2) already dust... use staircase in Z:
  //   dust (ox+3,oy,oz-3) -> block(ox+3,oy,oz-2)+dust(ox+3,oy+1,oz-2)
  //   -> block(ox+3,oy+1,oz-1)+dust(ox+3,oy+2,oz-1)
  //   -> dust(ox+3,oy+2,oz)   [crosses OVER A which is at y=oy]
  //   -> dust(ox+3,oy+2,oz+1)
  //   -> descend mirror: block(ox+3,oy+1,oz+1)+dust... then to lampB
  const bx = ox + 3;
  await sb(bx, oy, oz - 3, 'minecraft:redstone_wire');            // B start (driverB placed here later)
  await sb(bx, oy, oz - 2, 'minecraft:stone');                    // stair block 1
  await sb(bx, oy + 1, oz - 2, 'minecraft:redstone_wire');        // climb
  await sb(bx, oy + 1, oz - 1, 'minecraft:stone');                // stair block 2
  await sb(bx, oy + 2, oz - 1, 'minecraft:redstone_wire');        // climb to top
  // support block under the crossing dust so it isn't floating; this block sits
  // directly above A's wire (ox+3,oy,oz) -> block at (bx,oy+1,oz)
  await sb(bx, oy + 1, oz, 'minecraft:stone');                    // support over A
  await sb(bx, oy + 2, oz, 'minecraft:redstone_wire');            // crossing dust (y+2, over A)
  await sb(bx, oy + 1, oz + 1, 'minecraft:stone');                // descend stair
  await sb(bx, oy + 2, oz + 1, 'minecraft:redstone_wire');
  await sb(bx, oy + 1, oz + 2, 'minecraft:redstone_wire');        // step down (climb-down)
  await sb(bx, oy, oz + 2, 'minecraft:stone');                    // ground block
  await sb(bx, oy, oz + 3, 'minecraft:redstone_lamp');            // lampB
  await sleep(400);
  return {
    driverA: [ox, oy, oz], lampA: [ox + 6, oy, oz],
    driverB: [bx, oy, oz - 3], lampB: [bx, oy, oz + 3],
    // driverB drives its start dust; we put block one south of it:
    injA: [ox, oy, oz], injB: [bx, oy, oz - 3],
  };
}

async function run4(g) {
  let pass = 0;
  for (const [a, b] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
    // drive A: put redstone_block just west of A-start dust => at (ox,oy,oz) is dust; drive from (ox-1)
    await sb(g.injA[0] - 1, g.injA[1], g.injA[2], a ? 'minecraft:redstone_block' : 'minecraft:air');
    await sb(g.injB[0], g.injB[1], g.injB[2] - 1, b ? 'minecraft:redstone_block' : 'minecraft:air');
    await sleep(1000);
    const la = litP(...g.lampA), lb = litP(...g.lampB);
    const ok = (la === a && lb === b);
    pass += ok ? 1 : 0;
    console.log(`   A=${a} B=${b} -> lampA=${la} lampB=${lb} ${ok ? 'OK' : 'X (coupling!)'}`);
  }
  return pass;
}

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const oy = Math.floor(p.y);
  const ox = Math.floor(p.x) + 40, oz = Math.floor(p.z) + 40;
  C(`/tp riscv_xover ${ox} ${oy + 4} ${oz}`); await sleep(1200);
  console.log(`[xover] V1 up-and-over at ${ox},${oy},${oz}`);
  const g1 = await buildVariant1(ox, oy, oz);
  // ensure A start voxel is dust (driver injects from west)
  await sb(g1.injA[0], g1.injA[1], g1.injA[2], 'minecraft:redstone_wire');
  const pass1 = await run4(g1);
  console.log(`[xover] V1 up-and-over: ${pass1}/4 ${pass1 === 4 ? 'PASS — crossover works' : 'FAIL'}`);
  finish(pass1 === 4 ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 120000);
