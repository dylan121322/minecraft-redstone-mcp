import { Bot } from 'mineflayer';
import { Vec3 } from 'vec3';

/**
 * Terrain detector utility for Minecraft bots.
 * Provides ground level detection, world type inference, and safe building Y coordinates.
 */

export interface TerrainInfo {
    /** Y coordinate of the ground surface directly below the bot */
    groundY: number;
    /** Recommended Y level for placing circuits (groundY or groundY+1) */
    buildY: number;
    /** Inferred world type */
    worldType: 'superflat' | 'default' | 'unknown';
    /** Whether the world appears to be superflat (flat grass at constant Y) */
    isSuperflat: boolean;
    /** The block type at ground level */
    groundBlock: string;
    /** Number of blocks scanned downward before finding ground */
    scanDepth: number;
}

/**
 * Scan downward from the bot's current position to find the ground surface.
 * Stops at the first non-air, non-liquid block.
 *
 * @param bot - Mineflayer bot instance
 * @returns TerrainInfo with ground level and world type
 */
export function findGroundLevel(bot: Bot): TerrainInfo {
    const botPos = bot.entity.position;
    const startY = Math.floor(botPos.y);
    let groundY = startY;
    let groundBlock = 'air';
    let scanDepth = 0;

    // Scan downward from bot position
    for (let dy = 0; dy >= -20; dy--) {
        const checkY = startY + dy;
        const pos = new Vec3(Math.floor(botPos.x), checkY, Math.floor(botPos.z));
        const block = bot.blockAt(pos);

        if (!block) continue;

        const name = block.name || '';
        scanDepth = Math.abs(dy);

        // Skip air and liquids
        if (name === 'air' || name === 'cave_air' || name === 'void_air' ||
            name === 'water' || name === 'lava') {
            continue;
        }

        // Found solid ground
        groundY = checkY;
        groundBlock = name;
        break;
    }

    // Detect world type heuristics
    const isSuperflat = groundBlock === 'grass_block' && scanDepth <= 2;
    const worldType = isSuperflat ? 'superflat' :
                      (scanDepth > 5 ? 'default' : 'unknown');

    return {
        groundY,
        buildY: groundY,           // Place circuits directly on ground
        worldType,
        isSuperflat,
        groundBlock,
        scanDepth,
    };
}

/**
 * Get a safe Y coordinate for building, avoiding air gaps.
 * For superflat worlds: use groundY directly (grass surface).
 * For default worlds: use groundY + 1 (one block above ground).
 *
 * @param bot - Mineflayer bot instance
 * @param preferredY - Optional user-specified Y coordinate (overrides auto-detection)
 * @returns Safe building Y coordinate
 */
export function getBuildY(bot: Bot, preferredY?: number): number {
    if (preferredY !== undefined && preferredY !== null) {
        return preferredY;
    }

    const terrain = findGroundLevel(bot);
    return terrain.buildY;
}

/**
 * Ensure a solid block exists at the given position for redstone dust support.
 * If the position is air, places a stone block.
 * Uses /setblock via bot.chat().
 *
 * @param bot - Mineflayer bot instance
 * @param x - X coordinate
 * @param y - Y coordinate
 * @param z - Z coordinate
 */
export function ensureSupport(bot: Bot, x: number, y: number, z: number): void {
    const pos = new Vec3(x, y, z);
    const block = bot.blockAt(pos);
    if (!block || block.name === 'air' || block.name === 'cave_air') {
        bot.chat(`/setblock ${x} ${y} ${z} minecraft:stone`);
    }
}

/**
 * Place a block at the given position with terrain-aware Y adjustment.
 *
 * @param bot - Mineflayer bot instance
 * @param dx - Relative X from circuit origin
 * @param dy - Relative Y from circuit origin (0 = ground level)
 * @param dz - Relative Z from circuit origin
 * @param originX - Circuit origin X
 * @param originY - Circuit origin Y (ground level from terrain detection)
 * @param originZ - Circuit origin Z
 * @param block - Block ID string (minecraft:...)
 */
export function placeBlockAt(
    bot: Bot,
    dx: number, dy: number, dz: number,
    originX: number, originY: number, originZ: number,
    block: string
): void {
    const absX = Math.floor(originX + dx);
    const absY = Math.floor(originY + dy);
    const absZ = Math.floor(originZ + dz);
    bot.chat(`/setblock ${absX} ${absY} ${absZ} ${block}`);
}

/**
 * Clear an area above ground level for circuit building.
 * Preserves the ground layer (does not clear below groundY).
 *
 * @param bot - Mineflayer bot instance
 * @param x1 - Min X
 * @param z1 - Min Z
 * @param x2 - Max X
 * @param z2 - Max Z
 * @param groundY - Ground Y level to preserve
 * @param clearHeight - How many blocks above ground to clear (default: 4)
 */
export function clearBuildArea(
    bot: Bot,
    x1: number, z1: number,
    x2: number, z2: number,
    groundY: number,
    clearHeight: number = 4
): void {
    // Clear ABOVE ground only — preserve the ground surface
    bot.chat(`/fill ${x1} ${groundY} ${z1} ${x2} ${groundY + clearHeight} ${z2} minecraft:air`);
}
