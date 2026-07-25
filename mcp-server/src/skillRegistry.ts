import { Bot } from 'mineflayer';
import { BotWithLogger } from './types.js';
import { readdir } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath, pathToFileURL } from 'url';
import { existsSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));

export interface SkillDefinition {
    name: string;
    description: string;
    inputSchema: {
        type: string;
        properties: Record<string, any>;
        required: string[];
    };
    execute: (bot: BotWithLogger, args: any) => Promise<any>;
}

export class SkillRegistry {
    private skills: Map<string, SkillDefinition> = new Map();

    registerSkill(skill: SkillDefinition): void {
        this.skills.set(skill.name, skill);
    }

    getSkill(name: string): SkillDefinition | undefined {
        return this.skills.get(name);
    }

    getAllSkills(): SkillDefinition[] {
        return Array.from(this.skills.values());
    }
}

// Map of skill names to their descriptions and parameter schemas
const SKILL_METADATA: Record<string, { description: string; params: Record<string, any>; required: string[] }> = {
    attackSomeone: {
        description: "Attack, kill, defend against, or initiate combat with someone",
        params: {
            targetType: { type: "string", description: "The type of target: 'player', 'mob', or 'animal'" },
            targetName: { type: "string", description: "Optional: The specific name of the entity to attack" },
            duration: { type: "number", description: "Optional: Duration in seconds to attack (default: 20, max: 120)" },
            count: { type: "number", description: "Optional: Number of kills to achieve (default: 1)" }
        },
        required: ["targetType"]
    },
    buildRedstoneCircuit: {
        description: "Build a standard redstone circuit in Minecraft at the specified position. Supports logic gates (NOT, OR, AND, XOR, NAND, NOR, XNOR), sequential circuits (RS_NOR_LATCH, T_FLIPFLOP, EDGE_DETECTOR), arithmetic (HALF_ADDER), clocks (REPEATER_CLOCK, HOPPER_CLOCK), and contraptions (PISTON_DOOR_2X2, ITEM_SORTER). IMPORTANT: Use simulateRedstoneCircuit first to verify the circuit before building.",
        params: {
            circuit: {
                type: "string",
                description: "Circuit name. One of: NOT, OR, AND, XOR, NAND, NOR, XNOR, RS_NOR_LATCH, T_FLIPFLOP, HALF_ADDER, REPEATER_CLOCK, HOPPER_CLOCK, PISTON_DOOR_2X2, ITEM_SORTER, EDGE_DETECTOR, RIPPLE_CARRY_ADDER"
            },
            x: { type: "number", description: "Base X coordinate (circuit origin, input side)" },
            y: { type: "number", description: "Base Y coordinate" },
            z: { type: "number", description: "Base Z coordinate (circuit origin, input side)" },
            facing: { type: "string", description: "Circuit orientation: east (default, output faces east), north, south, or west" },
            bits: { type: "number", description: "Bit width for parameterized circuits (default: 4)" }
        },
        required: ["circuit", "x", "y", "z"]
    },
    cookItem: {
        description: "Cook an item in a furnace",
        params: {
            itemName: { type: "string", description: "The name of the item to cook" },
            fuelName: { type: "string", description: "The fuel to use for cooking" },
            count: { type: "number", description: "Number of items to cook" }
        },
        required: ["itemName", "fuelName", "count"]
    },
    craftItems: {
        description: "Craft items using a crafting table or inventory",
        params: {
            item: { type: "string", description: "The name of the item to craft" },
            count: { type: "number", description: "Number of items to craft" }
        },
        required: ["item", "count"]
    },
    dance: {
        description: "Make the bot dance by moving and jumping",
        params: {
            time: { type: "number", description: "Duration to dance in seconds (default: 10)" },
            name: { type: "string", description: "Optional: Name of the dance move" }
        },
        required: []
    },
    diffRedstoneCircuit: {
        description: "Compare two redstone circuit templates and compute the minimal block differences for incremental rebuild. Returns lists of blocks to add, remove, and modify — avoiding full circuit rebuild.",
        params: {
            circuitA: {
                type: "string",
                description: "Original circuit template JSON (inline string or object with 'blocks' array)"
            },
            circuitB: {
                type: "string",
                description: "Modified circuit template JSON (inline string or object with 'blocks' array)"
            }
        },
        required: ["circuitA", "circuitB"]
    },
    dropItem: {
        description: "Drop items from inventory",
        params: {
            name: { type: "string", description: "Name of the item to drop" },
            count: { type: "number", description: "Optional: Number of items to drop (default: all)" },
            userName: { type: "string", description: "Optional: Drop near a specific player" }
        },
        required: ["name"]
    },
    eatFood: {
        description: "Eat food from inventory to restore hunger",
        params: {},
        required: []
    },
    equipItem: {
        description: "Equip an item (armor, tool, or weapon)",
        params: {
            name: { type: "string", description: "Name of the item to equip" }
        },
        required: ["name"]
    },
    giveItemToSomeone: {
        description: "Give items to another player",
        params: {
            userName: { type: "string", description: "Username of the player to give items to" },
            itemName: { type: "string", description: "Name of the item to give" },
            itemCount: { type: "number", description: "Number of items to give" }
        },
        required: ["userName", "itemName", "itemCount"]
    },
    goToKnownLocation: {
        description: "Navigate to specific coordinates",
        params: {
            x: { type: "number", description: "X coordinate" },
            y: { type: "number", description: "Y coordinate" },
            z: { type: "number", description: "Z coordinate" },
            name: { type: "string", description: "Optional: Name of the location" }
        },
        required: ["x", "y", "z"]
    },
    goToSomeone: {
        description: "Navigate to another player",
        params: {
            userName: { type: "string", description: "Username of the player to go to" },
            distance: { type: "number", description: "Distance to maintain from the player (default: 3)" },
            keepFollowing: { type: "boolean", description: "Continue following the player (default: false)" }
        },
        required: ["userName"]
    },
    harvestMatureCrops: {
        description: "Harvest mature crops from nearby farmland",
        params: {
            number: { type: "number", description: "Number of crops to harvest" },
            radius: { type: "number", description: "Search radius (default: 30)" }
        },
        required: []
    },
    hunt: {
        description: "Hunt animals or mobs",
        params: {
            targetType: { type: "string", description: "Type of target: 'animal' or 'mob'" },
            targetName: { type: "string", description: "Optional: Specific name of the target" },
            amount: { type: "number", description: "Number to hunt (default: 1)" },
            duration: { type: "number", description: "Max duration in seconds (default: 60)" }
        },
        required: ["targetType"]
    },
    mineResource: {
        description: "Mine specific blocks or resources",
        params: {
            name: { type: "string", description: "Name of the block/resource to mine" },
            count: { type: "number", description: "Number of blocks to mine" }
        },
        required: ["name", "count"]
    },
    openInventory: {
        description: "Open the bot's inventory",
        params: {},
        required: []
    },
    openNearbyChest: {
        description: "Open a nearby chest",
        params: {},
        required: []
    },
    pickupItem: {
        description: "Pick up items from the ground",
        params: {
            itemName: { type: "string", description: "Name of the item to pick up" }
        },
        required: ["itemName"]
    },
    placeItemNearYou: {
        description: "Place a block or item near the bot",
        params: {
            itemName: { type: "string", description: "Name of the item/block to place" },
            userName: { type: "string", description: "Optional: Place near a specific player" }
        },
        required: ["itemName"]
    },
    prepareLandForFarming: {
        description: "Prepare land for farming by tilling soil",
        params: {},
        required: []
    },
    rest: {
        description: "Rest to regain health",
        params: {
            restTime: { type: "number", description: "Time to rest in seconds (default: 10)" }
        },
        required: []
    },
    retrieveItemsFromNearbyFurnace: {
        description: "Retrieve smelted items from a nearby furnace",
        params: {},
        required: []
    },
    runAway: {
        description: "Run away from a threat",
        params: {
            targetType: { type: "string", description: "Type of threat: 'player', 'mob', or 'animal'" },
            targetName: { type: "string", description: "Optional: Specific name of the threat" },
            runDistance: { type: "number", description: "Distance to run away (default: 20)" }
        },
        required: ["targetType"]
    },
    sleepInNearbyBed: {
        description: "Find and sleep in a nearby bed",
        params: {
            maxDistance: { type: "number", description: "Maximum distance to search for bed (default: 30)" }
        },
        required: []
    },
    smeltItem: {
        description: "Smelt items in a furnace",
        params: {
            itemName: { type: "string", description: "Name of the item to smelt" },
            fuelName: { type: "string", description: "Name of the fuel to use" },
            count: { type: "number", description: "Number of items to smelt" }
        },
        required: ["itemName", "fuelName", "count"]
    },
    swimToLand: {
        description: "Swim to the nearest land when in water",
        params: {},
        required: []
    },
    useItemOnBlockOrEntity: {
        description: "Use an item on a block or entity",
        params: {
            item: { type: "string", description: "Name of the item to use" },
            target: { type: "string", description: "Target block or entity" },
            count: { type: "number", description: "Optional: Number of times to use (default: 1)" }
        },
        required: ["item", "target"]
    },
    lookAround: {
        description: "Look around and observe the environment, providing a detailed text-based view of surroundings",
        params: {},
        required: []
    },
    buildSomething: {
        description: "Build structures using Minecraft commands (requires cheats/operator permissions). Supports two modes: 1) buildScript - array of command objects like [{\"command\": \"fill\", \"x1\": 0, \"y1\": 64, \"z1\": 0, \"x2\": 10, \"y2\": 70, \"z2\": 10, \"block\": \"stone\"}], 2) code - JavaScript string for dynamic building like \"for(let i = 0; i < 10; i++) { setBlock(pos.x + i, pos.y, pos.z, 'stone'); }\"",
        params: {
            buildScript: {
                type: "array",
                description: "Array of build commands. Supported commands: setblock (place single block), fill (fill region), clone (copy region), summon (spawn entities), give (give items), raw (execute raw command). Each command is an object with command type and parameters.",
                items: {
                    type: "object",
                    properties: {
                        command: {
                            type: "string",
                            description: "The command type: setblock, fill, clone, summon, give, or raw"
                        },
                        // Common properties for various commands
                        x: { type: "number", description: "X coordinate (for setblock)" },
                        y: { type: "number", description: "Y coordinate (for setblock)" },
                        z: { type: "number", description: "Z coordinate (for setblock)" },
                        x1: { type: "number", description: "Start X coordinate (for fill/clone)" },
                        y1: { type: "number", description: "Start Y coordinate (for fill/clone)" },
                        z1: { type: "number", description: "Start Z coordinate (for fill/clone)" },
                        x2: { type: "number", description: "End X coordinate (for fill/clone)" },
                        y2: { type: "number", description: "End Y coordinate (for fill/clone)" },
                        z2: { type: "number", description: "End Z coordinate (for fill/clone)" },
                        dx: { type: "number", description: "Destination X coordinate (for clone)" },
                        dy: { type: "number", description: "Destination Y coordinate (for clone)" },
                        dz: { type: "number", description: "Destination Z coordinate (for clone)" },
                        block: { type: "string", description: "Block type (for setblock/fill)" },
                        mode: { type: "string", description: "Mode (for fill/clone)" },
                        entity: { type: "string", description: "Entity type (for summon)" },
                        item: { type: "string", description: "Item type (for give)" },
                        count: { type: "number", description: "Item count (for give)" },
                        raw: { type: "string", description: "Raw command string (for raw command)" }
                    },
                    required: ["command"]
                }
            },
            code: {
                type: "string",
                description: "JavaScript code string for dynamic building. Available functions: setBlock(x,y,z,block), fill(x1,y1,z1,x2,y2,z2,block,mode?), clone(x1,y1,z1,x2,y2,z2,dx,dy,dz,mode?), summon(entity,x?,y?,z?), give(item,count?), execute(command), wait(ticks), log(message). Variables: bot, pos (bot position), Math, shouldStop()."
            }
        },
        required: [] // Neither is required, but one must be provided (checked in skill)
    },
    buildPixelArt: {
        description: "Build pixel art from an image in Minecraft (requires cheats/operator permissions). Converts an image to pixel art using colored blocks. Maximum size is 256x256 blocks.",
        params: {
            imagePath: {
                type: "string",
                description: "Path or URL to the image file to convert to pixel art"
            },
            width: {
                type: "number",
                description: "Width of the pixel art in blocks (max 256)"
            },
            height: {
                type: "number",
                description: "Height of the pixel art in blocks (max 256)"
            },
            x: {
                type: "number",
                description: "X coordinate for the bottom middle of the pixel art"
            },
            y: {
                type: "number",
                description: "Y coordinate for the bottom of the pixel art"
            },
            z: {
                type: "number",
                description: "Z coordinate for the bottom middle of the pixel art"
            },
            facing: {
                type: "string",
                description: "Direction the pixel art faces: 'north', 'south', 'east', or 'west' (default: 'north')"
            }
        },
        required: ["imagePath", "width", "height", "x", "y", "z"]
    },
    readChat: {
        description: "Read recent chat messages from the server. Returns player messages, system messages, whispers, action bar messages, and titles.",
        params: {
            count: {
                type: "number",
                description: "Number of recent messages to return (default: 20, max: 100)"
            },
            timeLimit: {
                type: "number",
                description: "Only return messages from the last N seconds (optional)"
            },
            filterType: {
                type: "string",
                description: "Filter by message type: 'all', 'chat', 'whisper', 'system', 'actionbar', 'title' (default: 'all')"
            },
            filterUsername: {
                type: "string",
                description: "Filter messages by specific username (optional)"
            }
        },
        required: []
    },
    sendChat: {
        description: "Send chat messages or commands to the server. Can send regular messages, commands (starting with /), or whispers.",
        params: {
            message: {
                type: "string",
                description: "The message or command to send (max 256 characters)"
            },
            delay: {
                type: "number",
                description: "Optional delay in milliseconds before sending (default: 0, max: 5000)"
            }
        },
        required: ["message"]
    },
    scanRedstoneCircuit: {
        description: "Scan a rectangular region in Minecraft and detect redstone circuits. Identifies components, builds a signal graph, and recognizes known circuit patterns (NOT, AND, RS NOR Latch). Outputs structured JSON for use with buildRedstoneCircuit or diffRedstoneCircuit.",
        params: {
            x1: { type: "number", description: "First corner X coordinate" },
            y1: { type: "number", description: "First corner Y coordinate" },
            z1: { type: "number", description: "First corner Z coordinate" },
            x2: { type: "number", description: "Second corner X coordinate" },
            y2: { type: "number", description: "Second corner Y coordinate" },
            z2: { type: "number", description: "Second corner Z coordinate" },
            autoAnalyze: { type: "boolean", description: "Auto-recognize circuit patterns (default: true)" }
        },
        required: ["x1", "y1", "z1", "x2", "y2", "z2"]
    },
    simulateRedstoneCircuit: {
        description: "Simulate a redstone circuit using the Nucleation engine to verify correctness BEFORE building. Runs all truth table test vectors automatically and returns PASS/FAIL with detailed timing analysis. ALWAYS simulate before calling buildRedstoneCircuit.",
        params: {
            circuit: {
                type: "string",
                description: "Circuit JSON template (inline JSON string) or circuit name matching buildRedstoneCircuit"
            },
            testInputs: {
                type: "array",
                description: "Optional custom test vectors as [{inputs: {A:1,B:0}, expected: {Q:0}}]. If omitted, auto-generates from truth table."
            },
            autoTest: {
                type: "boolean",
                description: "Auto-test all truth table combinations (default: true)"
            },
            ticks: {
                type: "number",
                description: "Simulation ticks to run per test vector (default: 40)"
            }
        },
        required: ["circuit"]
    }
};

export async function loadSkills(): Promise<SkillDefinition[]> {
    const skills: SkillDefinition[] = [];

    for (const [skillName, metadata] of Object.entries(SKILL_METADATA)) {
        skills.push({
            name: skillName,
            description: metadata.description,
            inputSchema: {
                type: "object",
                properties: metadata.params,
                required: metadata.required
            },
            execute: createSkillExecutor(skillName)
        });
    }

    return skills;
}

// Create a skill executor that loads and runs the actual skill code
function createSkillExecutor(skillName: string) {
    return async (bot: BotWithLogger, args: any): Promise<any> => {
        console.error(`[MCP] Executing skill '${skillName}' with args:`, args);

        try {
            // Path to the compiled skill bundled with the MCP server
            // __dirname is at: mcp-server/dist
            // Skills are at: mcp-server/dist/skills/verified
            const skillModulePath = join(__dirname, 'skills', 'verified', `${skillName}.js`);
            console.error(`[MCP] Loading skill from: ${skillModulePath}`);

            // Check if the skill file exists
            if (!existsSync(skillModulePath)) {
                throw new Error(
                    `Skill implementation not found at ${skillModulePath}. ` +
                    `Please ensure the MCP server was built correctly with 'npm run build'.`
                );
            }

            // Convert file path to file URL for proper ES module import
            const skillModuleUrl = pathToFileURL(skillModulePath).href;
            console.error(`[MCP] Importing skill from URL: ${skillModuleUrl}`);

            const skillModule = await import(skillModuleUrl);
            console.error(`[MCP] Skill module loaded successfully`);

            // Get the skill function
            const skillFunction = skillModule[skillName] || skillModule.default;
            if (!skillFunction) {
                throw new Error(`Skill function '${skillName}' not found in module`);
            }

            // Set up event listeners BEFORE executing the skill
            const observations: string[] = [];
            const textObservations: string[] = [];
            let startObservationSet = false;

            const startObservationHandler = (message: string) => {
                console.error(`[MCP] Bot start observation: ${message}`);
                startObservationSet = true;
                observations.push(message);
            };

            const textObservationHandler = (message: string) => {
                console.error(`[MCP] Bot text observation: ${message}`);
                textObservations.push(message);
            };

            const endObservationHandler = (message: string) => {
                console.error(`[MCP] Bot end observation: ${message}`);
                observations.push(message);
            };

            // Add event listeners
            (bot as any).on('alteraBotStartObservation', startObservationHandler);
            (bot as any).on('alteraBotTextObservation', textObservationHandler);
            (bot as any).on('alteraBotEndObservation', endObservationHandler);

            // Create service parameters with necessary functions
            const abortController = new AbortController();
            const serviceParams = {
                signal: abortController.signal,
                cancelExecution: () => {
                    console.error(`[MCP] Skill '${skillName}' execution cancelled`);
                    abortController.abort();
                },
                resetTimeout: () => {
                    console.error(`[MCP] Skill '${skillName}' timeout reset`);
                },
                getStatsData: () => {
                    console.error(`[MCP] Skill '${skillName}' requested stats data`);
                    return {};
                },
                setStatsData: (data: any) => {
                    console.error(`[MCP] Skill '${skillName}' set stats data:`, data);
                }
            };

            // Execute the skill with simple parameters (skills now expect plain objects)
            console.error(`[MCP] Calling skill function with args:`, args);
            let result;

            try {
                result = await skillFunction(bot, args, serviceParams);
                console.error(`[MCP] Skill '${skillName}' returned:`, result);
            } finally {
                // Always remove event listeners
                (bot as any).removeListener('alteraBotStartObservation', startObservationHandler);
                (bot as any).removeListener('alteraBotTextObservation', textObservationHandler);
                (bot as any).removeListener('alteraBotEndObservation', endObservationHandler);
            }

            // Format the response
            let response = '';

            // If we have observations, format them nicely
            if (observations.length > 0 || textObservations.length > 0) {
                // Add start observation if any
                if (startObservationSet && observations.length > 0) {
                    response += observations[0] + '\n';
                }

                // Add text observations
                if (textObservations.length > 0) {
                    response += '\n' + textObservations.join('\n') + '\n';
                }

                // Add end observation if any
                if (observations.length > 1) {
                    response += '\n' + observations[observations.length - 1];
                } else if (observations.length === 1 && !startObservationSet) {
                    response += observations[0];
                }

                console.error(`[MCP] Skill '${skillName}' returning observation response:`, response.substring(0, 100) + '...');
                return response.trim();
            }

            // If no observations but we have a result, return it
            if (result !== undefined && result !== null) {
                const resultStr = String(result);
                console.error(`[MCP] Skill '${skillName}' returning result as string:`, resultStr);
                return resultStr;
            }

            // Default response
            const defaultResponse = `Skill '${skillName}' executed successfully`;
            console.error(`[MCP] Skill '${skillName}' returning default response:`, defaultResponse);
            return defaultResponse;
        } catch (error) {
            console.error(`[MCP] Error executing skill '${skillName}':`, error);
            throw new Error(`Failed to execute skill '${skillName}': ${error instanceof Error ? error.message : String(error)}`);
        }
    };
} 