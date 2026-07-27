// test_wire_torch.cjs — the REAL operating condition of a NOT gate in a routed
// circuit: the input arrives as redstone_wire (dust), not a hard block.
// Under /setblock (no neighbor updates), does a dust->mount->torch chain update?
// We drive the dust with a redstone_block at its far end, then read torch lit.
//
// E) dust line -> mount(stone) -> wall_torch : block--dust--dust--MOUNT | torch on east
// F) dust sitting directly ON TOP of the block feeding a torch beside it
// G) The KNOWN-GOOD form: signal wire runs UNDER/INTO a solid, torch on top of that solid
//    (standing torch on a block that a wire points into)
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_wt', auth: 'offline' });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (c, m) => { if (done) return; done = true; if (m) console.log(m); try { bot.quit(); } catch {} setTimeout(() => process.exit(c), 300); };
bot.on('error', e => finish(1, `ERR ${e.message}`));
const C = s => bot.chat(s);
const prop = (x, y, z, k) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return null; const p = b.getProperties ? b.getProperties() : {}; return { n: b.name, v: p[k] }; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const by = Math.floor(p.y);
  const ox = Math.floor(p.x) + 20, oz = Math.floor(p.z) - 20;
  C(`/tp riscv_wt ${ox} ${by} ${oz}`); await sleep(800);
  console.log(`[wt] base ${ox},${by},${oz}`);
  for (let dx = -1; dx <= 12; dx++) for (let dz = -1; dz <= 6; dz++) { C(`/setblock ${ox + dx} ${by} ${oz + dz} minecraft:air`); C(`/setblock ${ox + dx} ${by - 1} ${oz + dz} minecraft:stone`); }
  await sleep(700);

  // E) block - wire - wire - mount(stone) with wall_torch on east face; wire strong-powers mount
  //    layout z=oz: [block]@0 [wire]@1 [wire]@2 [mount]@3 [torch east]@4
  let z = oz;
  C(`/setblock ${ox + 1} ${by} ${z} minecraft:redstone_wire`); await sleep(120);
  C(`/setblock ${ox + 2} ${by} ${z} minecraft:redstone_wire`); await sleep(120);
  C(`/setblock ${ox + 3} ${by} ${z} minecraft:stone`); await sleep(120);       // mount
  C(`/setblock ${ox + 4} ${by} ${z} minecraft:redstone_wall_torch[facing=east]`); await sleep(300);
  C(`/setblock ${ox + 0} ${by} ${z} minecraft:redstone_block`); await sleep(1400); // drive dust
  const E = prop(ox + 4, by, z, 'lit');
  console.log(`[E dust->mount->walltorch] ${JSON.stringify(E)} (want lit=false when driven)`);

  // G) standing torch on top of a block the wire points INTO (classic inverter):
  //    wire@0 -> solid@1 (wire points east into it), standing torch on top of solid@1
  z = oz + 3;
  C(`/setblock ${ox + 1} ${by} ${z} minecraft:stone`); await sleep(120);           // the powered block
  C(`/setblock ${ox + 1} ${by + 1} ${z} minecraft:redstone_torch`); await sleep(120); // standing torch on top
  C(`/setblock ${ox + 0} ${by} ${z} minecraft:redstone_wire`); await sleep(120);   // wire feeding it
  C(`/setblock ${ox - 1} ${by} ${z} minecraft:redstone_block`); await sleep(1400); // drive the wire
  const G = prop(ox + 1, by + 1, z, 'lit');
  console.log(`[G wire->block, standing torch on top] ${JSON.stringify(G)} (want lit=false when driven)`);

  // Also probe the driven wire actually carries (sanity)
  const w = prop(ox + 1, by, oz, 'power');
  console.log(`[E wire@mount-1 power] ${JSON.stringify(w)}`);

  finish(0, 'DONE');
});
setTimeout(() => finish(3, 'TIMEOUT'), 55000);
