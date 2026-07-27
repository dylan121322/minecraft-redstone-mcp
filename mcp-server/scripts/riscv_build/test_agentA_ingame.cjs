// test_agentA_ingame.cjs — build Agent A's exact bridge gadget IN-GAME (/setblock,
// no block updates) and confirm it conducts + isolates from a crossing obstacle.
// Gadget (from make_bridge((5,4),(15,4),0)):
//   rep@6,0 block@7,0+dust@7,1 block@8,1+dust@8,2 [supports 9-13 @y1 + dust@y2]
//   block@14,0+dust@14,1 dust@15,0
// Obstacle: y0 dust line crossing at x=10, z=0..8, its own driver+lamp.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_a', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 400); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const G = 65;
const sb = async (x, y, z, s) => { C(`/setblock ${x} ${y} ${z} ${s}`); await sleep(G); };
const lit = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; if (p.lit !== undefined) return p.lit ? 1 : 0; if (p.power !== undefined) return Number(p.power) > 0 ? 1 : 0; return 0; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const OY = Math.floor(p.y);
  const OX = Math.floor(p.x) + 40, OZ = Math.floor(p.z) + 40;  // origin; bridge runs +x at z=OZ+4
  C(`/tp riscv_a ${OX + 8} ${OY + 5} ${OZ + 4}`); await sleep(1200);
  console.log(`[A] origin ${OX},${OY},${OZ}`);
  C(`/fill ${OX - 2} ${OY - 1} ${OZ - 2} ${OX + 18} ${OY + 4} ${OZ + 10} minecraft:air`); await sleep(400);
  C(`/fill ${OX - 2} ${OY - 1} ${OZ - 2} ${OX + 18} ${OY - 1} ${OZ + 10} minecraft:stone`); await sleep(300);

  const bz = OZ + 4;   // bridge z
  // bridge source wire at (5,bz) driven from (4,bz)
  await sb(OX + 5, OY, bz, 'minecraft:redstone_wire');
  // gadget
  await sb(OX + 6, OY, bz, 'minecraft:repeater[facing=west]');
  await sb(OX + 7, OY, bz, 'minecraft:stone'); await sb(OX + 7, OY + 1, bz, 'minecraft:redstone_wire');
  await sb(OX + 8, OY + 1, bz, 'minecraft:stone'); await sb(OX + 8, OY + 2, bz, 'minecraft:redstone_wire');
  for (let rx = 9; rx <= 13; rx++) { await sb(OX + rx, OY + 1, bz, 'minecraft:stone'); await sb(OX + rx, OY + 2, bz, 'minecraft:redstone_wire'); }
  await sb(OX + 14, OY, bz, 'minecraft:stone'); await sb(OX + 14, OY + 1, bz, 'minecraft:redstone_wire');
  await sb(OX + 15, OY, bz, 'minecraft:redstone_wire');
  await sb(OX + 16, OY, bz, 'minecraft:redstone_lamp');  // bridge lamp

  // obstacle: y0 dust at x=OX+10, z=OZ..OZ+8, driver at z=OZ-1 area, lamp at z=OZ+9
  for (let z = OZ; z <= OZ + 8; z++) { if (z === bz) continue; await sb(OX + 10, OY, z, 'minecraft:redstone_wire'); }
  // the crossing point (OX+10, bz) is under the bridge — obstacle must pass there on y0.
  // put obstacle y0 dust AT (OX+10,bz) too (it's 2 below the bridge y2 dust w/ y1 block between)
  await sb(OX + 10, OY, bz, 'minecraft:redstone_wire');
  await sb(OX + 10, OY, OZ + 9, 'minecraft:redstone_lamp'); // obstacle lamp

  await sleep(500);
  let pass = 0;
  for (const [bd, od] of [[0, 0], [1, 0], [0, 1], [1, 1]]) {
    await sb(OX + 4, OY, bz, bd ? 'minecraft:redstone_block' : 'minecraft:air');        // bridge driver
    await sb(OX + 10, OY, OZ - 1, od ? 'minecraft:redstone_block' : 'minecraft:air');    // obstacle driver
    await sleep(1100);
    const lb = lit(OX + 16, OY, bz), lo = lit(OX + 10, OY, OZ + 9);
    const ok = (lb === bd && lo === od);
    pass += ok ? 1 : 0;
    console.log(`   bridge=${bd} obst=${od} -> lampB=${lb} lampO=${lo} ${ok ? 'OK' : 'X'}`);
  }
  console.log(`[A] in-game bridge: ${pass}/4 ${pass === 4 ? 'PASS — gadget works under /setblock' : 'FAIL'}`);
  finish(pass === 4 ? 0 : 42, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 120000);
