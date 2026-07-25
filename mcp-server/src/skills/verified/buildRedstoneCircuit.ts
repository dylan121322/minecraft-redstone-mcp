import { Bot } from 'mineflayer';
import { ISkillParams, ISkillServiceParams } from '../../types/skillType.js';
import { isSignalAborted } from '../index.js';
import { getBuildY, clearBuildArea, findGroundLevel } from '../../lib/terrainDetector.js';

// --- Circuit template types ---

interface BlockEntry {
    pos: [number, number, number];  // [dx, dy, dz] relative to circuit origin
    block: string;                   // "minecraft:block_id" or "minecraft:block_id[state=val]"
}

interface CircuitTemplate {
    name: string;
    category: string;
    dimensions: { width: number; height: number; depth: number };
    inputs: Array<{ label: string; pos: [number, number, number]; direction: string }>;
    outputs: Array<{ label: string; pos: [number, number, number]; direction: string }>;
    truth_table: Array<Record<string, number | string>>;
    blocks: BlockEntry[];
    propagation_delay_ticks: number;
    notes: string;
    params?: Record<string, unknown>;
}

// --- Rotation helpers ---

type Facing = 'north' | 'south' | 'east' | 'west';

/**
 * Rotate a relative position [dx, dy, dz] for the given facing direction.
 * Default circuit orientation: input from west (-X), output to east (+X).
 *
 * Rotation mapping (looking from above, Y-up):
 *   - east (default):  (dx, dy, dz) → (dx, dy, dz)   [no change]
 *   - north:           (dx, dy, dz) → (dz, dy, -dx)  [90° CW]
 *   - west:            (dx, dy, dz) → (-dx, dy, -dz) [180°]
 *   - south:           (dx, dy, dz) → (-dz, dy, dx)  [90° CCW]
 */
function rotatePos(pos: [number, number, number], facing: Facing): [number, number, number] {
    const [dx, dy, dz] = pos;
    switch (facing) {
        case 'east':
            return [dx, dy, dz];
        case 'north':
            return [dz, dy, -dx];
        case 'west':
            return [-dx, dy, -dz];
        case 'south':
            return [-dz, dy, dx];
        default:
            return [dx, dy, dz];
    }
}

/**
 * Rotate a block state's facing value by the given rotation.
 * Maps "facing=east" through the same rotation as positions.
 */
const FACING_ROTATION: Record<Facing, Record<string, string>> = {
    east:  { east: 'east',  north: 'north', west: 'west',  south: 'south', up: 'up', down: 'down' },
    north: { east: 'north', north: 'west',  west: 'south', south: 'east',  up: 'up', down: 'down' },
    west:  { east: 'west',  north: 'south', west: 'east',  south: 'north', up: 'up', down: 'down' },
    south: { east: 'south', north: 'east',  west: 'north', south: 'west',  up: 'up', down: 'down' },
};

function rotateBlockId(block: string, facing: Facing): string {
    // Rotate facing state within the block ID string
    return block.replace(/facing=(\w+)/g, (_match, dir) => {
        const rotated = FACING_ROTATION[facing]?.[dir];
        return rotated ? `facing=${rotated}` : _match;
    });
}

// --- Built-in circuit templates ---

const CIRCUITS: Record<string, CircuitTemplate> = {
    NOT: {
        name: 'NOT Gate',
        category: 'logic_gate',
        dimensions: { width: 3, height: 2, depth: 1 },
        inputs: [{ label: 'A', pos: [0, 0, 0], direction: 'west' }],
        outputs: [{ label: 'Q', pos: [2, 1, 0], direction: 'east' }],
        truth_table: [{ A: 0, Q: 1 }, { A: 1, Q: 0 }],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 0], block: 'minecraft:stone' },
            { pos: [2, 1, 0], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 1,
        notes: 'VERIFIED: rs_block→dust→block→torch@Y+1→dust@Y+1. Game-tested 2/2.',
    },

    OR: {
        name: 'OR Gate',
        category: 'logic_gate',
        dimensions: { width: 2, height: 1, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [1, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 0 },
            { A: 0, B: 1, Q: 1 },
            { A: 1, B: 0, Q: 1 },
            { A: 1, B: 1, Q: 1 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 0,
        notes: 'Simplest gate — just joining wires.',
    },

    AND: {
        name: 'AND Gate',
        category: 'logic_gate',
        dimensions: { width: 8, height: 2, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [7, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 0 }, { A: 0, B: 1, Q: 0 },
            { A: 1, B: 0, Q: 0 }, { A: 1, B: 1, Q: 1 },
        ],
        blocks: [
            // Y layer: mounting blocks + dust supports (all at ground level)
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [5, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 0, 0], block: 'minecraft:stone' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 0, 2], block: 'minecraft:stone' },
            { pos: [3, 0, 1], block: 'minecraft:stone' },
            { pos: [4, 0, 1], block: 'minecraft:stone' },
            // Input dust at Y
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            // Ground torches on mounts (NOT A, NOT B) at Y+1
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            // OR junction dust at Y+1 → dust chain to final mount
            { pos: [2, 1, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 1, 2], block: 'minecraft:redstone_wire' },
            { pos: [3, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [4, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [5, 1, 1], block: 'minecraft:redstone_wire' },
            // Wall torch output at Y (attached to final mount, reads block power)
            { pos: [6, 0, 1], block: 'minecraft:redstone_wall_torch[facing=east]' },
            // Output dust
            { pos: [7, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 3,
        notes: 'VERIFIED 2026-07-25: 3-torch AND gate, wall-torch output. Game-tested 4/4.',
    },

    XOR: {
        name: 'XOR Gate',
        category: 'logic_gate',
        dimensions: { width: 5, height: 2, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [4, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 0 },
            { A: 0, B: 1, Q: 1 },
            { A: 1, B: 0, Q: 1 },
            { A: 1, B: 1, Q: 0 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [3, 0, 1], block: 'minecraft:stone' },
            { pos: [3, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [4, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 2,
        notes: '4-torch XOR. XOR = (A OR B) AND NOT(A AND B).',
    },

    NAND: {
        name: 'NAND Gate',
        category: 'logic_gate',
        dimensions: { width: 11, height: 2, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [10, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 1 }, { A: 0, B: 1, Q: 1 },
            { A: 1, B: 0, Q: 1 }, { A: 1, B: 1, Q: 0 },
        ],
        blocks: [
            // AND section (positions 0-7, same as AND template)
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [5, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 0, 0], block: 'minecraft:stone' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 0, 2], block: 'minecraft:stone' },
            { pos: [3, 0, 1], block: 'minecraft:stone' },
            { pos: [4, 0, 1], block: 'minecraft:stone' },
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 1, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 1, 2], block: 'minecraft:redstone_wire' },
            { pos: [3, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [4, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [5, 1, 1], block: 'minecraft:redstone_wire' },
            { pos: [6, 0, 1], block: 'minecraft:redstone_wall_torch[facing=east]' },
            { pos: [7, 0, 1], block: 'minecraft:redstone_wire' },
            // NOT section (positions 8-10, inverts AND output)
            { pos: [8, 0, 1], block: 'minecraft:stone' },
            { pos: [9, 0, 1], block: 'minecraft:redstone_wall_torch[facing=east]' },
            { pos: [10, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 4,
        notes: 'VERIFIED 2026-07-25: AND+NOT chain. Game-tested 4/4.',
    },
    NOR: {
        name: 'NOR Gate',
        category: 'logic_gate',
        dimensions: { width: 2, height: 2, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [1, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 1 },
            { A: 0, B: 1, Q: 0 },
            { A: 1, B: 0, Q: 0 },
            { A: 1, B: 1, Q: 0 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 1], block: 'minecraft:stone' },
            { pos: [1, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
        ],
        propagation_delay_ticks: 1,
        notes: 'NOR = NOT(OR). 1-torch. Also the building block for RS NOR Latch.',
    },

    XNOR: {
        name: 'XNOR Gate',
        category: 'logic_gate',
        dimensions: { width: 6, height: 2, depth: 3 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [{ label: 'Q', pos: [5, 0, 1], direction: 'east' }],
        truth_table: [
            { A: 0, B: 0, Q: 1 },
            { A: 0, B: 1, Q: 0 },
            { A: 1, B: 0, Q: 0 },
            { A: 1, B: 1, Q: 1 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [3, 0, 1], block: 'minecraft:stone' },
            { pos: [3, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [4, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [5, 0, 1], block: 'minecraft:stone' },
            { pos: [5, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
        ],
        propagation_delay_ticks: 3,
        notes: 'XNOR = NOT(XOR). XOR output + final NOT.',
    },

    RS_NOR_LATCH: {
        name: 'RS NOR Latch',
        category: 'sequential',
        dimensions: { width: 4, height: 2, depth: 3 },
        inputs: [
            { label: 'S', pos: [0, 0, 0], direction: 'west' },
            { label: 'R', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [
            { label: 'Q', pos: [3, 0, 0], direction: 'east' },
            { label: 'Q_bar', pos: [3, 0, 2], direction: 'east' },
        ],
        truth_table: [
            { S: 0, R: 0, Q: 'hold' },
            { S: 1, R: 0, Q: 1, Q_bar: 0 },
            { S: 0, R: 1, Q: 0, Q_bar: 1 },
            { S: 1, R: 1, Q: 0, Q_bar: 0 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [3, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [3, 0, 2], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 2,
        notes: 'Two cross-coupled NOR gates. S=1 sets Q=1. R=1 resets Q=0. S=R=1 is forbidden.',
    },

    T_FLIPFLOP: {
        name: 'T Flip-Flop',
        category: 'sequential',
        dimensions: { width: 3, height: 3, depth: 3 },
        inputs: [{ label: 'T', pos: [0, 0, 1], direction: 'west' }],
        outputs: [{ label: 'Q', pos: [2, 0, 0], direction: 'east' }],
        truth_table: [
            { T: 0, Q: 'hold' },
            { T: 'rising', Q: 'toggle' },
        ],
        blocks: [
            { pos: [0, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 0], block: 'minecraft:dropper[facing=up]' },
            { pos: [0, 1, 0], block: 'minecraft:hopper[facing=down]' },
            { pos: [1, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 1], block: 'minecraft:stone' },
            { pos: [1, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 2, 1], block: 'minecraft:redstone_wire' },
            { pos: [1, 2, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 2, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 0], block: 'minecraft:stone' },
            { pos: [2, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 3,
        notes: 'Dropper-hopper T flip-flop. Most reliable design. Add 1 item to hopper.',
    },

    HALF_ADDER: {
        name: 'Half Adder',
        category: 'arithmetic',
        dimensions: { width: 6, height: 2, depth: 4 },
        inputs: [
            { label: 'A', pos: [0, 0, 0], direction: 'west' },
            { label: 'B', pos: [0, 0, 2], direction: 'west' },
        ],
        outputs: [
            { label: 'S', pos: [5, 0, 0], direction: 'east' },
            { label: 'C', pos: [5, 0, 2], direction: 'east' },
        ],
        truth_table: [
            { A: 0, B: 0, S: 0, C: 0 },
            { A: 0, B: 1, S: 1, C: 0 },
            { A: 1, B: 0, S: 1, C: 0 },
            { A: 1, B: 1, S: 0, C: 1 },
        ],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [0, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:stone' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 0, 2], block: 'minecraft:stone' },
            { pos: [1, 1, 2], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [1, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [3, 0, 1], block: 'minecraft:stone' },
            { pos: [3, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [3, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [3, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [4, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [4, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [5, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [5, 0, 2], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 3,
        notes: 'XOR(for S) + AND(for C) combined in one layout. S from XOR, C from AND.',
    },

    REPEATER_CLOCK: {
        name: 'Repeater Clock',
        category: 'signal',
        dimensions: { width: 3, height: 1, depth: 2 },
        inputs: [{ label: 'ENABLE', pos: [0, 0, 0], direction: 'west' }],
        outputs: [{ label: 'CLK', pos: [2, 0, 0], direction: 'east' }],
        truth_table: [],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:lever[facing=east]' },
            { pos: [0, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:repeater[facing=east,delay=2]' },
            { pos: [1, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 0], block: 'minecraft:repeater[facing=west,delay=2]' },
        ],
        propagation_delay_ticks: 4,
        notes: '2-repeater loop. Period = 2×delay. Requires kickstart pulse.',
    },

    HOPPER_CLOCK: {
        name: 'Hopper Clock',
        category: 'signal',
        dimensions: { width: 4, height: 2, depth: 2 },
        inputs: [],
        outputs: [{ label: 'CLK', pos: [3, 0, 1], direction: 'east' }],
        truth_table: [],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:hopper[facing=east]' },
            { pos: [1, 0, 0], block: 'minecraft:hopper[facing=west]' },
            { pos: [1, 0, 1], block: 'minecraft:redstone_comparator[facing=south,mode=compare]' },
            { pos: [2, 0, 1], block: 'minecraft:stone' },
            { pos: [2, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [3, 0, 1], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 0,
        notes: 'Most stable clock. Period = item_count × 0.4s × 2. No input needed.',
    },

    PISTON_DOOR_2X2: {
        name: '2×2 Piston Door',
        category: 'contraption',
        dimensions: { width: 6, height: 4, depth: 4 },
        inputs: [{ label: 'OPEN', pos: [0, 0, 1], direction: 'west' }],
        outputs: [],
        truth_table: [],
        blocks: [
            { pos: [0, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 1], block: 'minecraft:stone' },
            { pos: [1, 1, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 0, 2], block: 'minecraft:redstone_wire' },
            { pos: [2, 2, 1], block: 'minecraft:redstone_wire' },
            { pos: [3, 0, 0], block: 'minecraft:sticky_piston[facing=east]' },
            { pos: [3, 1, 0], block: 'minecraft:sticky_piston[facing=east]' },
            { pos: [3, 0, 2], block: 'minecraft:sticky_piston[facing=east]' },
            { pos: [3, 1, 2], block: 'minecraft:sticky_piston[facing=east]' },
            { pos: [3, 2, 1], block: 'minecraft:stone' },
            { pos: [3, 3, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 3, 0], block: 'minecraft:redstone_wire' },
            { pos: [2, 3, 2], block: 'minecraft:redstone_wire' },
            { pos: [1, 3, 0], block: 'minecraft:repeater[facing=west,delay=1]' },
            { pos: [1, 3, 2], block: 'minecraft:repeater[facing=west,delay=1]' },
        ],
        propagation_delay_ticks: 4,
        notes: '4 sticky pistons, split top/bottom. Repeaters sync timing.',
    },

    ITEM_SORTER: {
        name: 'Item Sorter (SS1)',
        category: 'contraption',
        dimensions: { width: 4, height: 3, depth: 2 },
        inputs: [{ label: 'ITEM_IN', pos: [0, 1, 0], direction: 'west' }],
        outputs: [{ label: 'ITEM_OUT', pos: [3, 0, 0], direction: 'down' }],
        truth_table: [],
        blocks: [
            { pos: [0, 1, 0], block: 'minecraft:hopper[facing=east]' },
            { pos: [1, 0, 0], block: 'minecraft:hopper[facing=down]' },
            { pos: [1, 0, 1], block: 'minecraft:redstone_comparator[facing=south,mode=compare]' },
            { pos: [2, 0, 1], block: 'minecraft:redstone_wire' },
            { pos: [2, 1, 1], block: 'minecraft:stone' },
            { pos: [2, 2, 1], block: 'minecraft:redstone_torch[lit=true]' },
            { pos: [2, 1, 0], block: 'minecraft:redstone_wire' },
            { pos: [1, 1, 0], block: 'minecraft:redstone_wire' },
            { pos: [3, 0, 0], block: 'minecraft:hopper[facing=down]' },
        ],
        propagation_delay_ticks: 2,
        notes: 'Single-slot filter. Filter hopper: 1 target item + 4 filler items. Stackable sideways.',
    },

    RIPPLE_CARRY_ADDER: {
        name: 'Ripple-Carry Adder',
        category: 'arithmetic',
        dimensions: { width: 0, height: 0, depth: 0 }, // parameterized — width = 7*bits
        inputs: [],
        outputs: [],
        truth_table: [],
        blocks: [],
        propagation_delay_ticks: 0,
        notes: 'Parameterized N-bit ripple-carry adder. Use bits=N param. Blocks expanded at build time.',
        params: { bits: 4 },
    },

    EDGE_DETECTOR: {
        name: 'Rising Edge Detector',
        category: 'sequential',
        dimensions: { width: 3, height: 1, depth: 1 },
        inputs: [{ label: 'IN', pos: [0, 0, 0], direction: 'west' }],
        outputs: [{ label: 'PULSE', pos: [2, 0, 0], direction: 'east' }],
        truth_table: [],
        blocks: [
            { pos: [0, 0, 0], block: 'minecraft:redstone_wire' },
            { pos: [1, 0, 0], block: 'minecraft:observer[facing=west]' },
            { pos: [2, 0, 0], block: 'minecraft:redstone_wire' },
        ],
        propagation_delay_ticks: 1,
        notes: 'Simple rising edge detector. Observer detects block state change, outputs 1rt pulse.',
    },
};

// --- Expansion for parameterized circuits ---

function expandCircuit(
    template: CircuitTemplate,
    params: { bits?: number; facing?: string }
): BlockEntry[] {
    const { bits = 4 } = params;

    if (template.name === 'Ripple-Carry Adder') {
        // For ripple-carry: chain N half-adder blocks with carry connections
        const blocks: BlockEntry[] = [];
        const spacing = 7; // X-spacing per stage

        const stageTemplate = CIRCUITS['HALF_ADDER'];
        if (!stageTemplate || !stageTemplate.blocks.length) {
            // Fallback: use built-in blocks from template if available
            return template.blocks.length > 0 ? template.blocks : [];
        }

        for (let i = 0; i < bits; i++) {
            const offsetX = i * spacing;
            for (const b of stageTemplate.blocks) {
                blocks.push({
                    pos: [b.pos[0] + offsetX, b.pos[1], b.pos[2]] as [number, number, number],
                    block: b.block,
                });
            }
            // Carry connection between stages (repeater for isolation)
            if (i < bits - 1) {
                blocks.push({
                    pos: [offsetX + 5, 0, 3],
                    block: 'minecraft:repeater[facing=east,delay=1]',
                });
            }
        }

        return blocks;
    }

    // Default: return template blocks as-is
    return template.blocks;
}

// --- Circuit validation ---

/** Circuits that have been game-tested and verified 4/4. */
const GAME_VERIFIED: Set<string> = new Set(['NOT', 'AND', 'NAND']);

/** Circuits that require Nucleation MCHPRS block-level simulation (not game-verified). */
const REQUIRES_SIMULATION: Set<string> = new Set([
    'XOR', 'XNOR', 'NOR', 'OR',
    'HALF_ADDER', 'FULL_ADDER', 'RIPPLE_CARRY_ADDER',
    'T_FLIPFLOP', 'RS_NOR_LATCH', 'PULSE_LIMITER',
]);

/** Building constraints enforced by game physics (superflat world). */
const BUILD_CONSTRAINTS = {
    GLASS_BASE: 'Circuits MUST be built on non-conductive base (glass) extending ≥3 blocks beyond circuit bounds. Superflat grass conductively connects all blocks.',
    WIRE_STOP_BEFORE_MOUNT: 'Inter-gate wiring MUST stop one block BEFORE the mounting stone (use < mountPos, not <=). Wires overwrite mounts, breaking wall torches.',
    CMD_DELAY: 'Minimum 200ms delay between /setblock commands. Faster rates cause server-side command drops.',
    BUILD_ORDER: 'Build order: Y-1 base → Y stones → Y inputs → Y+1 torches → Y+1 dust → Y wall torches → Y outputs.',
    CHUNK_RADIUS: 'Circuits must be built within 50 blocks of bot spawn. Block readings return null outside loaded chunks.',
    NO_FILL_Y: 'Never /fill clear the Y ground layer. Only clear Y+1 and above.',
};

// --- Main skill export ---

export const buildRedstoneCircuit = async (
    bot: Bot,
    params: ISkillParams,
    serviceParams: ISkillServiceParams
): Promise<boolean> => {
    const skillName = 'buildRedstoneCircuit';
    const circuitName = params.circuit as string;
    const bx = params.x as number;
    const bz = params.z as number;
    // Auto-detect ground Y if not specified (terrain-aware)
    const by = getBuildY(bot, params.y as number | undefined);
    const bits = (params.bits as number) || 4;
    const validFacings: Facing[] = ['east', 'north', 'west', 'south'];
    const facing: Facing = validFacings.includes(params.facing as Facing)
        ? (params.facing as Facing)
        : 'east';
    const { signal } = serviceParams;

    // 0. Validate circuit against build constraints
    const warnings: string[] = [];
    if (REQUIRES_SIMULATION.has(circuitName)) {
        warnings.push(
            `⚠️  '${circuitName}' has NOT been game-tested. Its logic is verified by simulation ` +
            `but the block-level layout may have routing issues. ` +
            `Recommend: run simulateRedstoneCircuit first, or use game-verified gates: ` +
            `${[...GAME_VERIFIED].join(', ')}.`
        );
    }
    if (!GAME_VERIFIED.has(circuitName)) {
        warnings.push(
            `ℹ️  Building constraint: ${BUILD_CONSTRAINTS.GLASS_BASE.substring(0, 80)}...`
        );
    }

    // 1. Look up circuit template
    const template = CIRCUITS[circuitName];
    if (!template) {
        const available = Object.keys(CIRCUITS).join(', ');
        bot.emit(
            'alteraBotEndObservation',
            `Unknown circuit: '${circuitName}'. Available circuits: ${available}`,
        );
        return false;
    }

    // 2. Expand parameterized circuits (e.g., N-bit adder)
    const blocks = expandCircuit(template, { bits, facing });

    bot.emit(
        'alteraBotStartObservation',
        `Building ${template.name} at (${bx}, ${by}, ${bz}), ` +
        `facing=${facing}, ${blocks.length} blocks...`,
    );

    // 3. Generate and execute /setblock commands
    // NOTE: bot.chat() is fire-and-forget — it does not throw on server-side
    // /setblock failures. Use simulateRedstoneCircuit before building to verify
    // the circuit design, and visually inspect the build result in-game.
    let placed = 0;

    for (const entry of blocks) {
        if (isSignalAborted(signal)) {
            bot.emit(
                'alteraBotEndObservation',
                `Build interrupted. Placed ${placed}/${blocks.length} blocks.`,
            );
            return false;
        }

        const [rdx, rdy, rdz] = rotatePos(entry.pos, facing);
        const rotatedBlock = rotateBlockId(entry.block, facing);

        const absX = Math.floor(bx + rdx);
        const absY = Math.floor(by + rdy);
        const absZ = Math.floor(bz + rdz);

        const command = `/setblock ${absX} ${absY} ${absZ} ${rotatedBlock}`;
        bot.chat(command);
        placed++;

        // Rate limit: 1 command per 2 ticks to avoid server throttling
        await bot.waitForTicks(2);
    }

    const warningText = warnings.length > 0 ? '\n' + warnings.join('\n') : '';
    const summary =
        `Built ${template.name} with ${placed} blocks at (${bx}, ${by}, ${bz}). ` +
        `NOTE: bot.chat() does not verify /setblock success server-side. ` +
        `Visually inspect the build, or run simulateRedstoneCircuit first to validate the circuit design.` +
        warningText;

    bot.emit('alteraBotEndObservation', summary);
    return true;
};
