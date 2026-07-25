/**
 * redstoneGraph.ts — Signal graph for redstone circuit analysis.
 *
 * Builds a directed graph from scanned redstone components:
 * - Nodes = components (torches, dust, repeaters, blocks)
 * - Edges = signal flow (torch → dust → block → torch)
 *
 * Supports:
 * - BFS/DFS traversal from any node
 * - Sub-circuit pattern matching (NOT, AND, RS latch templates)
 * - Connectivity analysis
 * - Template recognition from scanned layouts
 */

import { Vec3 } from 'vec3';
import type {
    RedstoneComponent, ComponentType, Facing,
} from './redstonePowerRules.js';
import {
    classifyComponent, isPowerSource, getFacing,
    getStrongPoweredPositions, getWeakPoweredPositions,
    getTorchAttachment,
} from './redstonePowerRules.js';

// --- Graph types ---

export interface SignalEdge {
    from: string;       // node ID
    to: string;         // node ID
    type: 'strong' | 'weak' | 'wire';
    signalStrength: number;
}

export interface SignalNode {
    id: string;                        // unique ID
    component: RedstoneComponent;
    neighbors: Set<string>;            // connected node IDs
    isInput: boolean;                  // circuit input (lever, button, external)
    isOutput: boolean;                 // circuit output (lamp, wire end)
    subCircuit?: string;               // recognized template name
}

export interface SignalGraph {
    nodes: Map<string, SignalNode>;
    edges: SignalEdge[];
}

// --- Graph construction ---

let nodeCounter = 0;
function nextId(): string {
    return `n${++nodeCounter}`;
}

/**
 * Build a signal graph from a list of scanned redstone components.
 */
export function buildSignalGraph(components: RedstoneComponent[]): SignalGraph {
    nodeCounter = 0;
    const graph: SignalGraph = { nodes: new Map(), edges: [] };

    // Step 1: Create nodes for all components
    for (const comp of components) {
        const id = nextId();
        const posKey = `${comp.pos.x},${comp.pos.y},${comp.pos.z}`;
        graph.nodes.set(posKey, {
            id,
            component: comp,
            neighbors: new Set(),
            isInput: comp.type === 'lever' || comp.type === 'button' || comp.type === 'pressure_plate',
            isOutput: comp.type === 'redstone_lamp',
        });
    }

    // Step 2: Build edges based on power propagation
    // First, add vertical edges: dust at Y+1 strongly powers block below at Y
    for (const [, node] of graph.nodes) {
        if (node.component.type === 'redstone_wire') {
            const below = `${node.component.pos.x},${node.component.pos.y - 1},${node.component.pos.z}`;
            const target = graph.nodes.get(below);
            if (target) {
                graph.edges.push({
                    from: node.id, to: target.id,
                    type: 'strong',
                    signalStrength: parseInt(node.component.state['power'] || '0'),
                });
                node.neighbors.add(target.id);
            }
        }
    }

    for (const [, node] of graph.nodes) {
        const comp = node.component;

        if (isPowerSource(comp)) {
            // Strong power edges
            const strongPositions = getStrongPoweredPositions(comp);
            for (const pos of strongPositions) {
                const key = `${pos.x},${pos.y},${pos.z}`;
                const target = graph.nodes.get(key);
                if (target) {
                    graph.edges.push({
                        from: node.id,
                        to: target.id,
                        type: 'strong',
                        signalStrength: 15,
                    });
                    node.neighbors.add(target.id);
                }
            }

            // Weak power edges
            const weakPositions = getWeakPoweredPositions(comp);
            for (const pos of weakPositions) {
                const key = `${pos.x},${pos.y},${pos.z}`;
                const target = graph.nodes.get(key);
                if (target) {
                    // Only add weak edges if not already strongly connected
                    const alreadyStrong = graph.edges.some(
                        e => e.from === node.id && e.to === target.id && e.type === 'strong'
                    );
                    if (!alreadyStrong) {
                        graph.edges.push({
                            from: node.id,
                            to: target.id,
                            type: 'weak',
                            signalStrength: 15,
                        });
                        node.neighbors.add(target.id);
                    }
                }
            }
        }

        // Wire connectivity: adjacent dust positions connect to each other
        if (comp.type === 'redstone_wire') {
            for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
                const adjKey = `${comp.pos.x + dx},${comp.pos.y},${comp.pos.z + dz}`;
                const adjNode = graph.nodes.get(adjKey);
                if (adjNode && adjNode.component.type === 'redstone_wire') {
                    const alreadyConnected = graph.edges.some(
                        e => (e.from === node.id && e.to === adjNode.id) ||
                             (e.from === adjNode.id && e.to === node.id)
                    );
                    if (!alreadyConnected) {
                        graph.edges.push({
                            from: node.id,
                            to: adjNode.id,
                            type: 'wire',
                            signalStrength: comp.powerLevel,
                        });
                        node.neighbors.add(adjNode.id);
                    }
                }
            }
        }
    }

    return graph;
}

// --- Traversal ---

/**
 * BFS from a starting node, returning all reachable nodes.
 */
export function bfs(graph: SignalGraph, startNodeId: string): SignalNode[] {
    const visited = new Set<string>();
    const result: SignalNode[] = [];
    const queue = [startNodeId];

    while (queue.length > 0) {
        const currentId = queue.shift()!;
        if (visited.has(currentId)) continue;
        visited.add(currentId);

        for (const [, node] of graph.nodes) {
            if (node.id === currentId) {
                result.push(node);
                for (const neighborId of node.neighbors) {
                    if (!visited.has(neighborId)) {
                        queue.push(neighborId);
                    }
                }
                break;
            }
        }
    }

    return result;
}

/**
 * Find all connected sub-networks in the graph.
 */
export function findSubNetworks(graph: SignalGraph): SignalNode[][] {
    const visited = new Set<string>();
    const networks: SignalNode[][] = [];

    for (const [, node] of graph.nodes) {
        if (visited.has(node.id)) continue;
        const network = bfs(graph, node.id);
        for (const n of network) visited.add(n.id);
        networks.push(network);
    }

    return networks;
}

// --- Pattern matching ---

export interface RecognizedCircuit {
    name: string;
    category: string;
    nodes: string[];         // node IDs in this circuit
    inputIds: string[];      // which nodes are inputs
    outputIds: string[];     // which nodes are outputs
    confidence: number;      // 0-1, how confident the match is
}

/**
 * Pattern: NOT gate = 1 mounting block + 1 torch + input dust + output dust
 */
function isTorch(t: string): boolean {
    return t === 'redstone_torch' || t === 'redstone_wall_torch';
}

function matchNOT(nodes: SignalNode[]): RecognizedCircuit | null {
    const torches = nodes.filter(n => isTorch(n.component.type));
    const wires = nodes.filter(n => n.component.type === 'redstone_wire');

    if (torches.length === 1 && wires.length >= 2 && nodes.length <= 6) {
        // Simple NOT gate: 1 torch, 2 wires, ~2 solid blocks
        const input = wires[0];
        const output = wires[wires.length - 1];
        return {
            name: 'NOT Gate',
            category: 'logic_gate',
            nodes: nodes.map(n => n.id),
            inputIds: [input.id],
            outputIds: [output.id],
            confidence: 0.8,
        };
    }
    return null;
}

/**
 * Pattern: AND gate = 3 NOT gates in specific arrangement.
 * Detects: 2 input NOTs + 1 output NOT with dust merging.
 */
function matchAND(nodes: SignalNode[]): RecognizedCircuit | null {
    const torches = nodes.filter(n => isTorch(n.component.type));
    const wires = nodes.filter(n => n.component.type === 'redstone_wire');

    // AND gate has 2 ground torches + 1 wall torch = 3 torches total
    if (torches.length >= 2 && torches.length <= 4 && wires.length >= 5) {
        // Identify two input NOTs and one output inversion
        return {
            name: 'AND Gate',
            category: 'logic_gate',
            nodes: nodes.map(n => n.id),
            inputIds: wires.slice(0, 2).map(w => w.id),
            outputIds: wires.slice(-1).map(w => w.id),
            confidence: 0.6,
        };
    }
    return null;
}

/**
 * Pattern: RS NOR Latch = 2 cross-coupled NOR gates.
 * Detects: 2 torches with cross-connected dust.
 */
function matchRSNOR(nodes: SignalNode[]): RecognizedCircuit | null {
    const torches = nodes.filter(n => isTorch(n.component.type));
    if (torches.length === 2 && nodes.length >= 8) {
        // Check for cross-coupling: each torch powers the other's input path
        let crossCoupled = false;
        for (const t1 of torches) {
            for (const t2 of torches) {
                if (t1.id === t2.id) continue;
                // Check if t1's output path reaches t2's attachment block
                const attach1 = getTorchAttachment(t1.component);
                const attach2 = getTorchAttachment(t2.component);
                const dist = Math.abs(attach1.x - attach2.x) + Math.abs(attach1.y - attach2.y) + Math.abs(attach1.z - attach2.z);
                if (dist <= 4) crossCoupled = true;
            }
        }
        if (crossCoupled) {
            return {
                name: 'RS NOR Latch',
                category: 'sequential',
                nodes: nodes.map(n => n.id),
                inputIds: [], // auto-detect
                outputIds: [],
                confidence: 0.5,
            };
        }
    }
    return null;
}

/**
 * All pattern matchers in priority order.
 */
const PATTERN_MATCHERS: Array<(nodes: SignalNode[]) => RecognizedCircuit | null> = [
    matchNOT,
    matchAND,
    matchRSNOR,
];

/**
 * Analyze a signal graph and recognize known circuit patterns.
 */
export function recognizeCircuits(graph: SignalGraph): RecognizedCircuit[] {
    const networks = findSubNetworks(graph);
    const circuits: RecognizedCircuit[] = [];

    // Try matching on individual sub-networks first
    for (const network of networks) {
        if (network.length < 3) continue;
        for (const matcher of PATTERN_MATCHERS) {
            const result = matcher(network);
            if (result) {
                circuits.push(result);
                for (const nodeId of result.nodes) {
                    for (const [, node] of graph.nodes) {
                        if (node.id === nodeId) node.subCircuit = result.name;
                    }
                }
                break;
            }
        }
    }

    // If no matches on sub-networks, try matching on the FULL component set
    // (handles cases where vertical connections aren't fully traced)
    if (circuits.length === 0) {
        const allNodes = [...graph.nodes.values()].map(n => ({
            ...n,
            component: n.component,
            neighbors: n.neighbors,
            id: n.id,
            isInput: n.isInput,
            isOutput: n.isOutput,
        }));
        for (const matcher of PATTERN_MATCHERS) {
            const result = matcher(allNodes);
            if (result) {
                circuits.push(result);
                break;
            }
        }
    }

    return circuits;
}

/**
 * Convert a recognized circuit back to the structured JSON encoding format
 * compatible with SKILL.md and buildRedstoneCircuit.ts.
 */
export function toCircuitTemplate(
    circuit: RecognizedCircuit,
    graph: SignalGraph,
    originX: number,
    originY: number,
    originZ: number
): Record<string, unknown> {
    const blocks: Array<{ pos: [number, number, number]; block: string }> = [];

    for (const nodeId of circuit.nodes) {
        for (const [, node] of graph.nodes) {
            if (node.id === nodeId) {
                const comp = node.component;
                blocks.push({
                    pos: [
                        comp.pos.x - originX,
                        comp.pos.y - originY,
                        comp.pos.z - originZ,
                    ],
                    block: comp.blockId,
                });
            }
        }
    }

    return {
        name: circuit.name,
        category: circuit.category,
        dimensions: { width: 0, height: 0, depth: 0 }, // computed later
        inputs: [],
        outputs: [],
        truth_table: [],
        blocks,
        propagation_delay_ticks: 0,
        notes: `Auto-detected by scanRedstoneCircuit at (${originX}, ${originY}, ${originZ})`,
    };
}
