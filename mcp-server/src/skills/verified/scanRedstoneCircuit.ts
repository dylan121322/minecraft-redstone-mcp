import { Bot } from 'mineflayer';
import { Vec3 } from 'vec3';
import { ISkillParams, ISkillServiceParams } from '../../types/skillType.js';
import { isRedstoneComponent, classifyComponent, RedstoneComponent } from '../../lib/redstonePowerRules.js';
import { buildSignalGraph, recognizeCircuits, toCircuitTemplate } from '../../lib/redstoneGraph.js';

export const scanRedstoneCircuit = async (
    bot: Bot,
    params: ISkillParams,
    _serviceParams: ISkillServiceParams
): Promise<string> => {
    const x1 = params.x1 as number;
    const y1 = params.y1 as number;
    const z1 = params.z1 as number;
    const x2 = params.x2 as number;
    const y2 = params.y2 as number;
    const z2 = params.z2 as number;
    const autoAnalyze = params.autoAnalyze !== false;

    // Normalize bounds
    const minX = Math.min(x1, x2);
    const maxX = Math.max(x1, x2);
    const minY = Math.min(y1, y2);
    const maxY = Math.max(y1, y2);
    const minZ = Math.min(z1, z2);
    const maxZ = Math.max(z1, z2);

    const volume = (maxX - minX + 1) * (maxY - minY + 1) * (maxZ - minZ + 1);
    if (volume > 10000) {
        return `Scan region too large (${volume} blocks). Maximum is 10,000 blocks.`;
    }

    // Scan region
    const components: RedstoneComponent[] = [];
    let scanned = 0;
    let redstoneFound = 0;

    for (let x = minX; x <= maxX; x++) {
        for (let y = minY; y <= maxY; y++) {
            for (let z = minZ; z <= maxZ; z++) {
                scanned++;
                const block = bot.blockAt(new Vec3(x, y, z));
                if (!block) continue;

                const name = block.name || '';
                if (!isRedstoneComponent(name)) continue;

                redstoneFound++;
                const rawStates = block.getProperties ? block.getProperties() : {};
                const states: Record<string, string> = {};
                for (const [k, v] of Object.entries(rawStates)) {
                    states[k] = String(v);
                }
                components.push({
                    pos: new Vec3(x, y, z),
                    type: classifyComponent(name, states),
                    blockId: `minecraft:${name}`,
                    state: states,
                    powerLevel: parseInt(states['power'] || '0', 10),
                    isPowered: false,
                    isStrongPowered: false,
                });
            }
        }
    }

    const lines: string[] = [];
    lines.push(`Scanned ${scanned} blocks (${minX},${minY},${minZ}) → (${maxX},${maxY},${maxZ})`);
    lines.push(`Found ${redstoneFound} redstone components`);

    if (redstoneFound === 0) {
        lines.push('No redstone components found in this region.');
        return lines.join('\n');
    }

    // Build signal graph
    const graph = buildSignalGraph(components);
    lines.push(`Signal graph: ${graph.nodes.size} nodes, ${graph.edges.length} edges`);

    // Recognize circuits
    if (autoAnalyze) {
        const circuits = recognizeCircuits(graph);
        if (circuits.length > 0) {
            lines.push(`\nRecognized ${circuits.length} circuit(s):`);
            for (const c of circuits) {
                lines.push(`  - ${c.name} (${c.category}, confidence: ${(c.confidence * 100).toFixed(0)}%)`);
            }
        } else {
            lines.push('\nNo known circuit patterns recognized.');
        }

        // Output structured JSON for each recognized circuit
        for (const c of circuits) {
            const template = toCircuitTemplate(c, graph, minX, minY, minZ);
            lines.push(`\n--- ${c.name} ---`);
            lines.push(JSON.stringify(template, null, 2));
        }
    }

    // Component inventory
    const typeCounts: Record<string, number> = {};
    for (const c of components) {
        typeCounts[c.type] = (typeCounts[c.type] || 0) + 1;
    }
    lines.push('\nComponent inventory:');
    for (const [type, count] of Object.entries(typeCounts).sort()) {
        lines.push(`  ${type}: ${count}`);
    }

    return lines.join('\n');
};
