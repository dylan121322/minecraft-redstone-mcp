/**
 * cpu_builder.cjs — Hybrid block placer for Minecraft CPU construction.
 *
 * Strategy:
 * - /setblock for all torch-based circuits (stone, dust, torches, lamps)
 * - bot.placeBlock() physical placement for REPEATERS (requires proper init)
 * - Bot teleports next to each repeater position, looks at target, places
 */

const mineflayer = require('mineflayer');
const { Vec3 } = require('vec3');
const mineflayer_pathfinder = require('mineflayer-pathfinder');
const { pathfinder, Movements } = mineflayer_pathfinder;

const HOST = 'localhost';
const PORT = 44508;
const USERNAME = 'CPUBuilder';

// ============================================================
// HYBRID PLACER
// ============================================================

class HybridPlacer {
    constructor(bot) {
        this.bot = bot;
        // Pathfinder loaded after bot spawn (in buildCPU)
    }

    initPathfinder() {
        const bot = this.bot;
        bot.loadPlugin(pathfinder);
        bot.pathfinder.setMovements(new Movements(bot));
    }

    // Setblock for most blocks (fast, reliable)
    async setblock(x, y, z, block) {
        this.bot.chat(`/setblock ${x} ${y} ${z} ${block}`);
        await this.sleep(150);
    }

    // Physical placement for REPEATERS (requires proper init)
    async placeRepeater(x, y, z, facing) {
        const bot = this.bot;

        // CALIBRATED 2026-07-25 (port 61977 test):
        // Look east(-PI/2) AT target → placed faces WEST
        // Look west(PI/2) AT target → placed faces EAST
        // Look south(0) AT target → placed faces NORTH
        // Look north(PI) AT target → placed faces SOUTH
        //
        // KEY: stand on OPPOSITE side from desired facing, look AT target:
        const config = {
            east:  { sx: x+1, sz: z,   yaw:  Math.PI/2 },  // stand EAST, look WEST at target
            west:  { sx: x-1, sz: z,   yaw: -Math.PI/2 },  // stand WEST, look EAST at target
            south: { sx: x,   sz: z+1, yaw:  Math.PI },    // stand SOUTH, look NORTH at target
            north: { sx: x,   sz: z-1, yaw:  0 },          // stand NORTH, look SOUTH at target
        };
        const cfg = config[facing] || config['east'];

        // Teleport to position (stand on opposite side, one block above target)
        bot.chat(`/tp ${bot.username} ${cfg.sx} ${y+1} ${cfg.sz}`);
        await this.sleep(400);

        // Look AT the target block from where we stand
        await bot.look(cfg.yaw, 0);
        await this.sleep(300);

        // Give repeater
        bot.chat('/give ' + bot.username + ' repeater 1');
        await this.sleep(300);

        // Equip
        const rp = bot.inventory.items().find(i => i.name === 'repeater');
        if (!rp) {
            console.error(`  ⚠ No repeater in inventory, falling back to /setblock`);
            return this.setblock(x, y, z, `repeater[facing=${facing},delay=1]`);
        }
        await bot.equip(rp, 'hand');
        await this.sleep(300);

        // Reference block: the glass/stone below the repeater position
        const refBlock = bot.blockAt(new Vec3(x, y-1, z));
        if (!refBlock) {
            console.error(`  ⚠ No reference block at (${x},${y-1},${z}), falling back`);
            return this.setblock(x, y, z, `repeater[facing=${facing},delay=1]`);
        }

        // Place against the top face
        try {
            await bot.placeBlock(refBlock, new Vec3(0, 1, 0));
            console.log(`  ✅ repeater placed at (${x},${y},${z}) facing=${facing}`);
        } catch(e) {
            console.error(`  ⚠ placeBlock failed: ${e.message}, falling back`);
            return this.setblock(x, y, z, `repeater[facing=${facing},delay=1]`);
        }
        await this.sleep(300);
    }

    sleep(ms) {
        return new Promise(r => setTimeout(r, ms));
    }
}

// ============================================================
// CPU BUILDER
// ============================================================

async function buildCPU() {
    const bot = mineflayer.createBot({ host: HOST, port: PORT, username: USERNAME });
    const placer = new HybridPlacer(bot);
    const { sleep } = placer;

    return new Promise((resolve) => {
        bot.once('spawn', async () => {
            placer.initPathfinder();
            const GY = Math.floor(bot.entity.position.y);
            const X = Math.floor(bot.entity.position.x) + 5;
            const Z = Math.floor(bot.entity.position.z);
            const SP = 12;
            console.log(`GY=${GY}, X=${X}, Z=${Z}`);

            // Glass base
            bot.chat(`/fill ${X-5} ${GY-1} ${Z-5} ${X+55} ${GY-1} ${Z+25} minecraft:glass`);
            await sleep(3000);

            // Clear above ground
            bot.chat(`/fill ${X-5} ${GY} ${Z-5} ${X+55} ${GY+5} ${Z+25} minecraft:air`);
            await sleep(2000);

            // =========================================
            // ALU: 4 AND gates (all /setblock)
            // =========================================
            console.log('Building ALU (4 AND gates)...');
            for (let bit=0; bit<4; bit++) {
                const bx = X + bit*SP;
                // Stones
                for (const [dx,dz] of [[1,0],[1,2],[5,1],[2,0],[2,1],[2,2],[3,1],[4,1]])
                    await placer.setblock(bx+dx, GY, Z+dz, 'minecraft:stone');
                // Dust inputs
                await placer.setblock(bx, GY, Z, 'minecraft:redstone_wire');
                await placer.setblock(bx, GY, Z+2, 'minecraft:redstone_wire');
                // Torches
                await placer.setblock(bx+1, GY+1, Z, 'minecraft:redstone_torch');
                await placer.setblock(bx+1, GY+1, Z+2, 'minecraft:redstone_torch');
                // Dust routing
                for (const [dx,dz] of [[2,0],[2,1],[2,2],[3,1],[4,1],[5,1]])
                    await placer.setblock(bx+dx, GY+1, Z+dz, 'minecraft:redstone_wire');
                // Wall torch
                await placer.setblock(bx+6, GY, Z+1, 'minecraft:redstone_wall_torch[facing=east]');
                // Output dust
                await placer.setblock(bx+7, GY, Z+1, 'minecraft:redstone_wire');
                // ALU lamp
                await placer.setblock(bx+7, GY, Z+3, 'minecraft:redstone_lamp');
                await placer.setblock(bx+7, GY+1, Z+3, `minecraft:${[1,2,4,8][bit]===1?'white':[1,2,4,8][bit]===2?'light_gray':[1,2,4,8][bit]===4?'gray':'black'}_wool`);
                await sleep(100);
            }

            // =========================================
            // ACC REGISTER: 4 repeater locks (PHYSICAL repeaters)
            // =========================================
            console.log('\nBuilding ACC register (physical repeaters)...');
            const regZ = Z + 8;

            for (let bit=0; bit<3; bit++) {
                const bx = X + bit*SP;
                // Input dust
                await placer.setblock(bx, GY, regZ, 'minecraft:redstone_wire');
                // PHYSICAL REPEATER
                console.log(`  Placing repeater bit${bit}...`);
                await placer.placeRepeater(bx+1, GY, regZ, 'east');
                // Output dust
                await placer.setblock(bx+2, GY, regZ, 'minecraft:redstone_wire');
                // ACC lamp
                await placer.setblock(bx+3, GY, regZ, 'minecraft:redstone_lamp');
                await placer.setblock(bx+3, GY+1, regZ, `minecraft:${[1,2,4,8][bit]===1?'white':[1,2,4,8][bit]===2?'light_gray':[1,2,4,8][bit]===4?'gray':'black'}_wool`);
                // Register lock side (stone for lock signal)
                await placer.setblock(bx+1, GY, regZ+1, 'minecraft:stone');
            }

            // =========================================
            // CLOCK LINE
            // =========================================
            console.log('\nBuilding clock line...');
            const clockZ = regZ + 6;
            for (let px = X; px <= X+2*SP+1; px++)
                await placer.setblock(px, GY, clockZ, 'minecraft:redstone_wire');
            // Clock input position
            await placer.setblock(X-2, GY, clockZ, 'minecraft:stone');
            // Route clock to each register lock side
            for (let bit=0; bit<3; bit++) {
                const bx = X + bit*SP;
                for (let z=regZ+2; z<=clockZ; z++)
                    await placer.setblock(bx+1, GY, z, 'minecraft:redstone_wire');
            }

            // =========================================
            // DATA BUS: ALU output → Register input
            // =========================================
            console.log('\nBuilding data bus...');
            for (let bit=0; bit<3; bit++) {
                const bx = X + bit*SP;
                const aluOutX = bx+7, aluOutZ = Z+1;
                // PHYSICAL REPEATER for bus routing
                console.log(`  Placing bus repeater bit${bit}...`);
                await placer.placeRepeater(bx+8, GY, aluOutZ, 'south');
                // Dust from repeater south to register input at Z+8
                for (let z=aluOutZ+1; z<=regZ; z++)
                    await placer.setblock(bx+8, GY, z, 'minecraft:redstone_wire');
                // Wire west to register area — SKIP repeater position (bx+1)!
                for (let px=bx+8; px>bx+1; px--)
                    await placer.setblock(px, GY, regZ, 'minecraft:redstone_wire');
                // Wire at bx (register input) — repeater at bx+1 bridges the gap
                await placer.setblock(bx, GY, regZ, 'minecraft:redstone_wire');
            }

            console.log('\n✅ 4-bit CPU built!');
            console.log(`Location: X=${X}, Z=${Z}`);
            console.log(`Row 1 (Z+0): ALU (4 AND gates) — input A,B at dust positions`);
            console.log(`Row 2 (Z+8): ACC register (4 repeater locks) — clock at Z+14`);
            console.log(`Row 3: Data bus (ALU → Register)`);

            setTimeout(() => resolve(bot), 3000);
        });

        bot.on('error', e => { if(!e.message.includes('ECONNRESET')) console.error(e.message); });
        bot.on('kicked', r => { console.error('Kicked:', r); });
        setTimeout(() => resolve(bot), 300000); // 5 min max
    });
}

// Run
if (require.main === module) {
    buildCPU().then(bot => {
        console.log('Build complete. Bot staying connected for 60s...');
        setTimeout(() => bot.quit(), 60000);
    }).catch(e => { console.error(e); process.exit(1); });
}

module.exports = { HybridPlacer, buildCPU };
