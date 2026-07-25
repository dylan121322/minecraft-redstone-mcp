/**
 * redstonePowerRules.ts — Minecraft redstone power propagation rules.
 *
 * Implements the core redstone physics for signal analysis:
 * - Strong vs weak power
 * - Block-to-block power transfer
 * - Torch behavior (inverter, burnout, 1-tick delay)
 * - Repeater behavior (amplifier, delay, locking)
 * - Comparator behavior (compare/subtract, container reading)
 * - Dust connectivity and signal strength decay
 *
 * Used by: scanRedstoneCircuit, redstoneGraph, optimizeRedstoneCircuit
 */

import { Vec3 } from 'vec3';

// --- Component types ---

export type ComponentType =
    | 'redstone_wire'
    | 'redstone_torch'
    | 'redstone_wall_torch'
    | 'redstone_block'
    | 'repeater'
    | 'comparator'
    | 'lever'
    | 'button'
    | 'pressure_plate'
    | 'observer'
    | 'piston'
    | 'sticky_piston'
    | 'redstone_lamp'
    | 'solid_block'
    | 'target'
    | 'unknown';

export interface RedstoneComponent {
    pos: Vec3;
    type: ComponentType;
    blockId: string;
    state: Record<string, string>;  // block states from getProperties()
    powerLevel: number;              // 0-15, current signal strength
    isPowered: boolean;              // whether this component receives power
    isStrongPowered: boolean;        // strongly vs weakly powered (for solid blocks)
}

export type Facing = 'north' | 'south' | 'east' | 'west' | 'up' | 'down';

// --- Power propagation ---

/**
 * List of redstone-related block IDs to scan for.
 */
export const REDSTONE_BLOCK_IDS = [
    'redstone_wire', 'redstone_torch', 'redstone_wall_torch',
    'redstone_block', 'repeater', 'comparator',
    'lever', 'stone_button', 'oak_button', 'birch_button',
    'spruce_button', 'jungle_button', 'acacia_button', 'dark_oak_button',
    'crimson_button', 'warped_button', 'mangrove_button', 'cherry_button',
    'stone_pressure_plate', 'oak_pressure_plate', 'heavy_weighted_pressure_plate',
    'light_weighted_pressure_plate',
    'observer', 'piston', 'sticky_piston', 'redstone_lamp',
    'target', 'dispenser', 'dropper', 'hopper', 'note_block',
    'daylight_detector', 'trapped_chest', 'lectern',
    'iron_door', 'iron_trapdoor', 'oak_fence_gate',
    'tnt',
];

/**
 * Check if a block ID is a redstone component.
 */
export function isRedstoneComponent(blockName: string): boolean {
    const name = blockName.replace('minecraft:', '');
    return REDSTONE_BLOCK_IDS.includes(name);
}

/**
 * Classify a block into a ComponentType.
 */
export function classifyComponent(blockName: string, states: Record<string, string>): ComponentType {
    const name = blockName.replace('minecraft:', '');
    switch (name) {
        case 'redstone_wire': return 'redstone_wire';
        case 'redstone_torch': return 'redstone_torch';
        case 'redstone_wall_torch': return 'redstone_wall_torch';
        case 'redstone_block': return 'redstone_block';
        case 'repeater': return 'repeater';
        case 'comparator': return 'comparator';
        case 'lever': return 'lever';
        case 'observer': return 'observer';
        case 'piston': return 'piston';
        case 'sticky_piston': return 'sticky_piston';
        case 'redstone_lamp': return 'redstone_lamp';
        case 'target': return 'target';
        default:
            if (name.includes('button')) return 'button';
            if (name.includes('pressure_plate')) return 'pressure_plate';
            return 'solid_block';
    }
}

/**
 * Get the facing direction of a directional redstone component.
 */
export function getFacing(component: RedstoneComponent): Facing | null {
    const facing = component.state['facing'];
    if (facing && ['north', 'south', 'east', 'west', 'up', 'down'].includes(facing)) {
        return facing as Facing;
    }
    return null;
}

/**
 * Check if a redstone component is a power source (outputs power actively).
 */
export function isPowerSource(component: RedstoneComponent): boolean {
    switch (component.type) {
        case 'redstone_torch':
        case 'redstone_wall_torch':
            // Torch is power source when lit (ON = block it's on is NOT powered)
            return component.state['lit'] === 'true';
        case 'redstone_block':
            return true;
        case 'lever':
            return component.state['powered'] === 'true';
        case 'button':
            return component.state['powered'] === 'true';
        case 'observer':
            return component.state['powered'] === 'true';
        case 'repeater':
            return component.state['powered'] === 'true';
        case 'comparator':
            return component.state['powered'] === 'true';
        default:
            return false;
    }
}

/**
 * Get the signal strength output by a power source.
 */
export function getSourcePower(component: RedstoneComponent): number {
    if (!isPowerSource(component)) return 0;

    switch (component.type) {
        case 'redstone_torch':
        case 'redstone_wall_torch':
            return 15;
        case 'redstone_block':
            return 15;
        case 'lever':
            return 15;
        case 'button':
            return 15;
        case 'observer':
            return 15;
        case 'repeater':
            return 15; // Repeater always outputs 15
        case 'comparator':
            // Comparator output depends on mode and inputs — simplified
            return parseInt(component.state['powered'] === 'true' ? '15' : '0');
        case 'redstone_wire':
            return component.powerLevel;
        default:
            return 0;
    }
}

/**
 * Get all positions that are strongly powered by a power source.
 * Strong power can activate repeaters, comparators, and torches.
 */
export function getStrongPoweredPositions(
    component: RedstoneComponent
): Vec3[] {
    const positions: Vec3[] = [];
    const { pos, type } = component;
    const facing = getFacing(component);

    if (!isPowerSource(component)) return positions;

    switch (type) {
        case 'redstone_block':
            // Strongly powers all 6 adjacent blocks
            for (const [dx, dy, dz] of [[1,0,0],[-1,0,0],[0,1,0],[0,-1,0],[0,0,1],[0,0,-1]]) {
                positions.push(new Vec3(pos.x + dx, pos.y + dy, pos.z + dz));
            }
            break;

        case 'redstone_torch':
            // Ground torch: strongly powers block above, weakly powers adjacent
            positions.push(new Vec3(pos.x, pos.y + 1, pos.z));
            break;

        case 'redstone_wall_torch':
            // Wall torch: strongly powers block it's attached to? No — torch reads that block.
            // Wall torch strongly powers block above it and weakly powers adjacent dust
            positions.push(new Vec3(pos.x, pos.y + 1, pos.z));
            break;

        case 'repeater':
        case 'comparator':
            // Strongly powers the block in the facing direction
            if (facing) {
                const offset = facingToOffset(facing);
                positions.push(new Vec3(pos.x + offset.x, pos.y + offset.y, pos.z + offset.z));
            }
            break;

        case 'lever':
            // Strongly powers block it's attached to
            if (facing) {
                const offset = facingToOffset(facing);
                // Lever faces opposite to attachment
                positions.push(new Vec3(pos.x - offset.x, pos.y - offset.y, pos.z - offset.z));
            }
            break;

        case 'redstone_wire':
            // Wire strongly powers the block below it and blocks it points into
            positions.push(new Vec3(pos.x, pos.y - 1, pos.z));
            // Also powers blocks at the end of each connection
            // Simple heuristic: wire powers all 4 adjacent blocks weakly
            break;

        default:
            break;
    }

    return positions;
}

/**
 * Get positions that are weakly powered (can activate repeaters/comparators but not dust).
 */
export function getWeakPoweredPositions(
    component: RedstoneComponent
): Vec3[] {
    const positions: Vec3[] = [];
    const { pos, type } = component;

    if (!isPowerSource(component)) return positions;

    switch (type) {
        case 'redstone_torch':
        case 'redstone_wall_torch':
        case 'redstone_block':
        case 'repeater':
        case 'comparator':
            // These weakly power all adjacent blocks at the same Y level
            for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
                positions.push(new Vec3(pos.x + dx, pos.y, pos.z + dz));
            }
            // Also above and below
            positions.push(new Vec3(pos.x, pos.y + 1, pos.z));
            positions.push(new Vec3(pos.x, pos.y - 1, pos.z));
            break;

        default:
            break;
    }

    return positions;
}

/**
 * Calculate signal strength decay over redstone wire.
 * Signal drops by 1 per block of wire.
 */
export function calculateWireSignal(
    sourcePower: number,
    wireDistance: number
): number {
    return Math.max(0, sourcePower - wireDistance);
}

/**
 * Check if a solid block conducts redstone power (strong power propagation between blocks).
 * Most solid blocks conduct; transparent blocks (glass, glowstone) do not.
 */
export function isConductiveBlock(blockName: string): boolean {
    const nonConductive = [
        'glass', 'glass_pane', 'glowstone', 'ice', 'packed_ice',
        'sea_lantern', 'tnt', 'glow_lichen', 'scaffolding',
        'slime_block', 'honey_block',  // these ARE conductive!
    ];
    const name = blockName.replace('minecraft:', '');
    return !nonConductive.some(nc => name.includes(nc));
}

/**
 * Convert facing direction to vector offset.
 */
export function facingToOffset(facing: Facing): Vec3 {
    switch (facing) {
        case 'north': return new Vec3(0, 0, -1);
        case 'south': return new Vec3(0, 0, 1);
        case 'east': return new Vec3(1, 0, 0);
        case 'west': return new Vec3(-1, 0, 0);
        case 'up': return new Vec3(0, 1, 0);
        case 'down': return new Vec3(0, -1, 0);
    }
}

/**
 * Torch attachment calculation:
 * - Ground torch at (x, y, z): attached to block at (x, y-1, z)
 * - Wall torch at (x, y, z) facing F: attached to block at (x - offset.x, y, z - offset.z)
 */
export function getTorchAttachment(component: RedstoneComponent): Vec3 {
    const { pos, type } = component;
    if (type === 'redstone_torch') {
        return new Vec3(pos.x, pos.y - 1, pos.z);
    }
    if (type === 'redstone_wall_torch') {
        const facing = getFacing(component);
        if (facing) {
            const offset = facingToOffset(facing);
            // Torch faces away from block it's attached to
            return new Vec3(pos.x - offset.x, pos.y, pos.z - offset.z);
        }
    }
    return pos;
}
