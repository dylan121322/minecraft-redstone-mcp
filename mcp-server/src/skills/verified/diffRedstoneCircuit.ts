import { Bot } from 'mineflayer';
import { ISkillParams, ISkillServiceParams } from '../../types/skillType.js';

interface BlockEntry {
    pos: [number, number, number];
    block: string;
}

interface DiffResult {
    added: BlockEntry[];
    removed: BlockEntry[];
    modified: BlockEntry[];
    unchanged: number;
    totalChanges: number;
}

function posKey(pos: [number, number, number]): string {
    return `${pos[0]},${pos[1]},${pos[2]}`;
}

function computeDiff(
    circuitA: { blocks: BlockEntry[] },
    circuitB: { blocks: BlockEntry[] }
): DiffResult {
    const mapA = new Map<string, BlockEntry>();
    const mapB = new Map<string, BlockEntry>();

    for (const b of circuitA.blocks) {
        mapA.set(posKey(b.pos), b);
    }
    for (const b of circuitB.blocks) {
        mapB.set(posKey(b.pos), b);
    }

    const added: BlockEntry[] = [];
    const removed: BlockEntry[] = [];
    const modified: BlockEntry[] = [];
    let unchanged = 0;

    // Find added and modified
    for (const [key, bBlock] of mapB) {
        const aBlock = mapA.get(key);
        if (!aBlock) {
            added.push(bBlock);
        } else if (aBlock.block !== bBlock.block) {
            modified.push(bBlock);
        } else {
            unchanged++;
        }
    }

    // Find removed
    for (const [key, aBlock] of mapA) {
        if (!mapB.has(key)) {
            removed.push(aBlock);
        }
    }

    return {
        added,
        removed,
        modified,
        unchanged,
        totalChanges: added.length + removed.length + modified.length,
    };
}

export const diffRedstoneCircuit = async (
    _bot: Bot,
    params: ISkillParams,
    _serviceParams: ISkillServiceParams
): Promise<string> => {
    let circuitA: { blocks: BlockEntry[] };
    let circuitB: { blocks: BlockEntry[] };

    try {
        circuitA = typeof params.circuitA === 'string'
            ? JSON.parse(params.circuitA as string)
            : (params.circuitA as { blocks: BlockEntry[] });
        circuitB = typeof params.circuitB === 'string'
            ? JSON.parse(params.circuitB as string)
            : (params.circuitB as { blocks: BlockEntry[] });
    } catch {
        return 'Error: circuitA and circuitB must be valid JSON circuit templates (or objects with "blocks" array).';
    }

    if (!circuitA?.blocks || !circuitB?.blocks) {
        return 'Error: Both circuitA and circuitB must have a "blocks" array.';
    }

    const diff = computeDiff(circuitA, circuitB);

    const lines: string[] = [];
    lines.push(`Circuit diff: ${diff.totalChanges} total changes`);
    lines.push(`  Added:   ${diff.added.length} blocks`);
    lines.push(`  Removed: ${diff.removed.length} blocks`);
    lines.push(`  Modified: ${diff.modified.length} blocks`);
    lines.push(`  Unchanged: ${diff.unchanged} blocks`);
    lines.push('');

    if (diff.added.length > 0) {
        lines.push('--- Blocks to ADD ---');
        for (const b of diff.added.slice(0, 20)) {
            lines.push(`  /setblock ${b.pos[0]} ${b.pos[1]} ${b.pos[2]} ${b.block}`);
        }
        if (diff.added.length > 20) {
            lines.push(`  ... and ${diff.added.length - 20} more`);
        }
    }

    if (diff.removed.length > 0) {
        lines.push('\n--- Blocks to REMOVE ---');
        for (const b of diff.removed.slice(0, 20)) {
            lines.push(`  /setblock ${b.pos[0]} ${b.pos[1]} ${b.pos[2]} minecraft:air destroy`);
        }
        if (diff.removed.length > 20) {
            lines.push(`  ... and ${diff.removed.length - 20} more`);
        }
    }

    if (diff.modified.length > 0) {
        lines.push('\n--- Blocks to MODIFY ---');
        for (const b of diff.modified.slice(0, 20)) {
            lines.push(`  /setblock ${b.pos[0]} ${b.pos[1]} ${b.pos[2]} ${b.block}`);
        }
        if (diff.modified.length > 20) {
            lines.push(`  ... and ${diff.modified.length - 20} more`);
        }
    }

    // Summary for incremental build
    if (diff.totalChanges > 0) {
        lines.push(`\nIncremental build: ${diff.totalChanges} blocks to change vs full rebuild of ${circuitB.blocks.length} blocks`);
        const savings = circuitB.blocks.length - diff.totalChanges;
        if (savings > 0) {
            lines.push(`Savings: ${savings} blocks unchanged (${((savings / circuitB.blocks.length) * 100).toFixed(0)}%)`);
        }
    }

    return lines.join('\n');
};
