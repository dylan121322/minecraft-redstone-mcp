// test_activation.cjs — Does /setblock-placed redstone ACTIVATE neighbors on THIS server?
// This is the MC-31100 gate. If a torch doesn't invert a redstone_block input,
// no module will work here and we must stop before building anything.
//
// Layout at base (bx,by,bz), on a stone floor at by-1:
//   redstone_block(input) -> stone(mount) -> wall_torch(east) -> wire(output)
//   torch should be OFF when block present (block powers mount -> torch off).
//   Then remove block -> torch ON. We read the OUTPUT wire's power both ways.
const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');

const HOST = process.argv[2] || 'frp-tag.com';
const PORT = parseInt(process.argv[3] || '40269', 10);
const bot = mineflayer.createBot({ host: HOST, port: PORT, username: 'riscv_act', auth: 'offline' });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let done = false;
const finish = (code, msg) => { if (done) return; done = true; if (msg) console.log(msg); try { bot.quit(); } catch {} setTimeout(() => process.exit(code), 300); };
bot.on('error', e => finish(1, `[act] ERROR ${e.message}`));
bot.on('kicked', r => finish(1, `[act] KICKED ${JSON.stringify(r)}`));

const CMD = (s) => bot.chat(s);
const power = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); if (!b) return -1; const p = b.getProperties ? b.getProperties() : {}; return p.power !== undefined ? Number(p.power) : (b.metadata || 0); };
const nameAt = (x, y, z) => { const b = bot.blockAt(new Vec3(x, y, z)); return b ? b.name : 'null'; };

bot.once('spawn', async () => {
  const p = bot.entity.position;
  const bx = Math.floor(p.x) + 5, by = Math.floor(p.y), bz = Math.floor(p.z);
  console.log(`[act] base ${bx},${by},${bz} v${bot.version}`);

  // teleport bot near build so chunk is loaded & within setblock radius
  CMD(`/tp riscv_act ${bx} ${by} ${bz}`);
  await sleep(800);

  // floor
  for (let dx = -2; dx <= 4; dx++) CMD(`/setblock ${bx + dx} ${by - 1} ${bz} minecraft:stone`);
  await sleep(400);
  // clear layer
  for (let dx = -2; dx <= 4; dx++) CMD(`/setblock ${bx + dx} ${by} ${bz} minecraft:air`);
  await sleep(400);

  // NOT gate: input block at dx=0, mount at dx=1, wall_torch(east) at dx=2, output wire dx=3
  CMD(`/setblock ${bx + 1} ${by} ${bz} minecraft:stone`);            // mount
  await sleep(200);
  CMD(`/setblock ${bx + 2} ${by} ${bz} minecraft:redstone_wall_torch[facing=east]`); // torch
  await sleep(200);
  CMD(`/setblock ${bx + 3} ${by} ${bz} minecraft:redstone_wire`);    // output
  await sleep(200);

  // CASE A: input = 0 (no redstone_block). torch should be ON -> output powered.
  CMD(`/setblock ${bx + 0} ${by} ${bz} minecraft:air`);
  await sleep(1200);
  const outA = power(bx + 3, by, bz);
  const torchA = nameAt(bx + 2, by, bz);
  console.log(`[act] CASE input=0: torch=${torchA} output_power=${outA}  (expect ON/powered)`);

  // CASE B: input = 1 (redstone_block powers mount -> torch OFF -> output unpowered)
  CMD(`/setblock ${bx + 0} ${by} ${bz} minecraft:redstone_block`);
  await sleep(1200);
  const outB = power(bx + 3, by, bz);
  const torchB = nameAt(bx + 2, by, bz);
  console.log(`[act] CASE input=1: torch=${torchB} output_power=${outB}  (expect OFF/0)`);

  const invert = (outA > 0 && outB === 0);
  console.log(`[act] NOT behavior (out=~in): ${invert ? 'YES — redstone ACTIVATES, MC-31100 OK' : 'NO — /setblock redstone inert (need mod)'}`);
  finish(invert ? 0 : 42, invert ? '[act] PASS' : '[act] FAIL_INERT');
});

setTimeout(() => finish(3, '[act] TIMEOUT'), 40000);
