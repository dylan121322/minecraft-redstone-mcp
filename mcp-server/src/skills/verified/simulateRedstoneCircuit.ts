import { Bot } from 'mineflayer';
import { ISkillParams, ISkillServiceParams } from '../../types/skillType.js';
import { spawn } from 'child_process';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Circuit templates are imported from buildRedstoneCircuit for consistency
// For now, we accept circuit JSON directly or a circuit name

interface SimResult {
    passed: boolean;
    circuit_name: string;
    category: string;
    results: Array<{
        inputs: Record<string, number | string>;
        expected: Record<string, number | string>;
        actual: Record<string, number | string>;
        match: boolean;
        delay_ticks?: number;
    }>;
    timing: {
        propagation_delay_ticks: number;
        block_count?: number;
    };
    errors: string[];
    warnings: string[];
}

function callNucleationBridge(
    circuitData: Record<string, unknown>,
    testVectors: Array<Record<string, unknown>>,
    ticks: number
): Promise<SimResult> {
    return new Promise((resolve, reject) => {
        // Path from dist/skills/verified/ up to project root, then scripts/
        const scriptPath = join(__dirname, '..', '..', '..', 'scripts', 'nucleation_bridge.py');
        const py = spawn('python3', [scriptPath], {
            stdio: ['pipe', 'pipe', 'pipe'],
        });

        let stdout = '';
        let stderr = '';

        py.stdout.on('data', (data: Buffer) => {
            stdout += data.toString();
        });

        py.stderr.on('data', (data: Buffer) => {
            stderr += data.toString();
        });

        py.on('error', (err: Error) => {
            reject(new Error(`Failed to start Python bridge: ${err.message}. Is Python 3 installed?`));
        });

        py.on('close', (code: number | null) => {
            if (code !== 0) {
                reject(new Error(
                    `Python bridge exited with code ${code}. stderr: ${stderr.substring(0, 500)}`
                ));
                return;
            }

            try {
                const result = JSON.parse(stdout) as SimResult;
                resolve(result);
            } catch {
                reject(new Error(
                    `Failed to parse Python bridge output. stdout: ${stdout.substring(0, 500)}`
                ));
            }
        });

        const input = JSON.stringify({
            circuit: circuitData,
            test_vectors: testVectors,
            ticks: ticks,
        });

        py.stdin.write(input);
        py.stdin.end();
    });
}

/**
 * Build test vectors from truth table when autoTest is enabled.
 */
function buildTestVectors(
    circuit: Record<string, unknown>,
    customTestInputs?: Array<Record<string, number>>,
    autoTest?: boolean
): Array<Record<string, unknown>> {
    if (customTestInputs && customTestInputs.length > 0) {
        // Use custom test inputs — build expected from truth table lookup
        const truthTable = (circuit.truth_table as Array<Record<string, unknown>>) || [];
        return customTestInputs.map((inputs) => {
            const expected: Record<string, unknown> = {};
            for (const row of truthTable) {
                let allMatch = true;
                for (const [k, v] of Object.entries(inputs)) {
                    if (row[k] !== v) {
                        allMatch = false;
                        break;
                    }
                }
                if (allMatch) {
                    // Copy all non-input keys from row as expected outputs
                    for (const [k, v] of Object.entries(row)) {
                        if (!(k in inputs)) {
                            expected[k] = v;
                        }
                    }
                    break;
                }
            }
            return { inputs, expected };
        });
    }

    // Auto-generate from truth table
    if (autoTest === false) {
        return [];
    }

    const truthTable = (circuit.truth_table as Array<Record<string, unknown>>) || [];
    const testVectors: Array<Record<string, unknown>> = [];

    // Compute labels once (outside loop)
    const inputLabels = ((circuit.inputs as Array<{ label: string }>) || []).map((i) => i.label);
    const outputLabels = ((circuit.outputs as Array<{ label: string }>) || []).map((o) => o.label);

    for (const row of truthTable) {
        const inputs: Record<string, unknown> = {};
        const expected: Record<string, unknown> = {};

        for (const [k, v] of Object.entries(row)) {
            if (inputLabels.includes(k)) {
                inputs[k] = v;
            } else if (outputLabels.includes(k)) {
                expected[k] = v;
            } else if (k === 'Q' || k === "Q'" || k === 'Q_bar' ||
                       k === 'S' || k === 'C' || k === 'Cout' ||
                       k === 'CLK' || k === 'PULSE') {
                // Heuristic: common output labels
                expected[k] = v;
            }
        }

        // For sequential circuits with "hold"/"toggle" rows, skip auto-generation
        const hasStateMarkers = Object.values(expected).some(
            (v) => v === 'hold' || v === 'toggle' || v === 'rising' || v === 'oscillating'
        );

        if (Object.keys(inputs).length > 0 && Object.keys(expected).length > 0 && !hasStateMarkers) {
            testVectors.push({ inputs, expected });
        }
    }

    return testVectors;
}

function formatSimulationResult(result: SimResult): string {
    const lines: string[] = [];

    const statusIcon = result.passed ? '✅' : '❌';
    lines.push(`${statusIcon} Simulation: ${result.circuit_name} (${result.category})`);
    lines.push(`   Passed: ${result.passed}`);
    lines.push(`   Propagation delay: ${result.timing.propagation_delay_ticks} rt`);
    if (result.timing.block_count) {
        lines.push(`   Block count: ${result.timing.block_count}`);
    }
    lines.push('');

    // Results table
    lines.push('Test Results:');
    lines.push('─'.repeat(60));
    for (const r of result.results) {
        const inputsStr = Object.entries(r.inputs)
            .map(([k, v]) => `${k}=${v}`)
            .join(', ');
        const expectedStr = Object.entries(r.expected)
            .map(([k, v]) => `${k}=${v}`)
            .join(', ');
        const actualStr = Object.entries(r.actual)
            .map(([k, v]) => `${k}=${v}`)
            .join(', ');
        const matchIcon = r.match ? '✓' : '✗';
        lines.push(`  ${matchIcon} [${inputsStr}] → expected(${expectedStr}) actual(${actualStr})`);
        if (r.delay_ticks !== undefined && r.delay_ticks !== null) {
            lines.push(`    delay: ${r.delay_ticks} rt`);
        }
    }

    // Errors
    if (result.errors.length > 0) {
        lines.push('');
        lines.push('Errors:');
        for (const e of result.errors) {
            lines.push(`  ❌ ${e}`);
        }
    }

    // Warnings
    if (result.warnings.length > 0) {
        lines.push('');
        lines.push('Warnings:');
        for (const w of result.warnings) {
            lines.push(`  ⚠️ ${w}`);
        }
    }

    // Recommendation
    if (result.passed && result.errors.length === 0) {
        lines.push('');
        lines.push('✅ Circuit passed all tests. Safe to build with buildRedstoneCircuit.');
    } else {
        lines.push('');
        lines.push('❌ Circuit has errors. Fix the issues before building.');
    }

    return lines.join('\n');
}

export const simulateRedstoneCircuit = async (
    bot: Bot,
    params: ISkillParams,
    serviceParams: ISkillServiceParams
): Promise<string> => {
    const circuitParam = params.circuit as string;
    const testInputs = params.testInputs as Array<Record<string, number>> | undefined;
    const autoTest = params.autoTest !== undefined ? (params.autoTest as boolean) : true;
    const ticks = (params.ticks as number) || 40;

    let circuitData: Record<string, unknown>;

    // Parse circuit: could be a circuit name or raw JSON string/object
    try {
        if (typeof circuitParam === 'string') {
            circuitData = JSON.parse(circuitParam);
        } else if (typeof circuitParam === 'object' && circuitParam !== null) {
            circuitData = circuitParam as Record<string, unknown>;
        } else {
            throw new Error('circuit must be a JSON string or object');
        }
    } catch {
        throw new Error(
            `Circuit parameter is not valid JSON. ` +
            `Please provide the full circuit template as inline JSON ` +
            `with "name", "category", "blocks", "truth_table" fields. ` +
            `See the minecraft-redstone-coding skill for the JSON schema and templates.`
        );
    }

    // Validate required fields
    if (!circuitData.name || !circuitData.category) {
        throw new Error(
            'Circuit template must have "name" and "category" fields. ' +
            'See SKILL.md for the required JSON schema.'
        );
    }

    if (!circuitData.blocks || !Array.isArray(circuitData.blocks)) {
        throw new Error('Circuit template must have a "blocks" array.');
    }

    // Build test vectors
    const testVectors = buildTestVectors(circuitData, testInputs, autoTest);

    // Call Python bridge
    let result: SimResult;
    try {
        result = await callNucleationBridge(circuitData, testVectors, ticks);
    } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        throw new Error(`Simulation failed: ${msg}`);
    }

    // Format and return
    return formatSimulationResult(result);
};
