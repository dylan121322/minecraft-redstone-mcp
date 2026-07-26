# Minecraft Redstone MCP — AI 驱动的红石电路设计、仿真与建造系统

基于 [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) 的扩展，为 AI Agent 添加红石电路的结构化设计、仿真验证和游戏内自动建造能力。

## 架构

```
Verilog/VHDL → yosys 综合 → 门级网表 → 三维布局 → 迷宫布线 → 分层验证 → litematic/schematic
                                              ↓
                                     nucleation MCHPRS 物理仿真
                                              ↓
                               SKILL.md (红石知识库 + 建造约束)
```

**核心管道**：源代码 → 提取单元 → 红石代码重构 → 模拟 → 可建造输出。

## 三层能力体系

### 1. 知识层（SKILL.md 1485 行）
- 红石元件速查表（40+ 元件）
- 结构化电路编码格式（JSON schema，含真值表/时序）
- 标准电路目录（JSON 模板，NOT/AND/OR/XOR/RS锁存/T触发器/全加器）
- **建造约束与语法限制**：玻璃基底隔离、门间隔离、/setblock 命令速率、MC-31100 修复（Forge mod）、验证陷阱、**MCHPRS 仿真规则**（5 条实测）、区块加载约束
- **三维综合管道规则**：yosys 集成、分层验证、dust 密度 O(N²) 等

### 2. 仿真层（nucleation MCHPRS + 行为级 + 分层验证）
| 仿真方式 | 用途 | 规模上限 |
|---------|------|---------|
| MCHPRS 块级真红石仿真 | 单门/小电路物理验证（NOT 2/2、AND/OR/NAND/NOR 4/4） | ≤ 几门 |
| 行为级逻辑仿真 | netlist 功能验证（组合逻辑精确） | 无上限 |
| 分层验证（物理+逻辑） | 大规模电路绕过 redpiler 密度瓶颈：物理层每个 cell 独立 MCHPRS 验证 + 逻辑层 netlist 行为仿真 | **无上限** |

### 3. 执行层
| 方式 | 适用场景 |
|------|---------|
| Mineflayer Bot + /setblock | 小到中电路（命令速率 200ms/条，距离 ≤210 格） |
| litematic 导出 | 任意规模（游戏内一次性粘贴，绕过命令速率/距离限制） |
| Minecraft Forge mod (1.20.1/1.21.4) | 修复 MC-31100（/setblock 红石元件不激活） |

## 验证结果

### 游戏内验证（2026-07-25）
| 电路 | 测试结果 |
|------|---------|
| NOT Gate | 2/2 ✅ |
| AND Gate | 4/4 ✅ |
| NAND Gate (AND→NOT chain) | 4/4 ✅ |
| 3-bit 进位计算器 | 4/4 ✅ |

### MCHPRS 物理验证
| 电路 | 测试结果 |
|------|---------|
| 6 门标准单元（NOT/BUF/OR/AND/NAND/NOR） | 各 4/4 ✅ |
| 全加器（层验证：物理+逻辑） | 8/8 ✅ |
| 8-bit ALU（AND/OR/ADD/XOR/SUB，160 门） | 80/80 ✅ |
| 2×NOT 链（自动布线） | 2/2 ✅ |
| 扇出 x→2NOT→OR（自动布线） | 2/2 ✅ |

### RISC-V CPU 编译器（行为仿真）
| 电路 | 测试结果 |
|------|---------|
| 1-bit Full Adder | 4/4 ✅ |
| 8-bit RCA | 6/6 ✅ |
| RISC-V 5 级流水线全配置（32 寄存器，6226 门） | 12/12 ✅ |

## 快速开始

```bash
# 依赖
cd mcp-server && npm install && npm run build
pip install nucleation

# 可选（Verilog 综合）
brew install yosys   # macOS
```

Claude Desktop 配置 `claude_desktop_config.json`：
```json
{ "mcpServers": { "minecraft": { "command": "node", "args": ["/path/to/mcp-server/dist/mcp-server.js"] } } }
```

## redstone3d 包（三维大规模综合）

`mcp-server/scripts/redstone3d/` 提供完整的三维电路综合管道：

```
yosys_frontend.py → yosys abc 工业级综合（全加器 19→7 门，ALU→160 门）
cell_library.py   → 标准单元库（6 门，MCHPRS 全验证）
placer.py         → 拓扑分层三维布局（体素防重叠）
maze_router.py    → Lee 迷宫布线 + rip-up&reroute（协商式拥塞）
synth.py          → netlist→place→route→schematic
mchprs_sim.py     → redstone_block 注入式 MCHPRS 仿真（4ms/向量）
regress.py        → 分层验证（物理+逻辑，突破规模上限）
verify_alu8.py    → 8-bit ALU 端到端验证
```

## 文件结构

```
├── docs/SKILL.md                       # 红石知识库（1485 行）
├── mods/                               # Minecraft Forge mod (修复 MC-31100)
│   ├── forge-1.20.1/
│   └── forge-1.21.4/
├── mcp-server/
│   ├── src/
│   │   ├── skills/verified/
│   │   │   ├── buildRedstoneCircuit.ts    # 建造工具
│   │   │   ├── simulateRedstoneCircuit.ts # 仿真工具
│   │   │   ├── scanRedstoneCircuit.ts     # 扫描工具
│   │   │   └── diffRedstoneCircuit.ts     # 差异工具
│   │   ├── lib/
│   │   │   ├── terrainDetector.ts         # 地形检测
│   │   │   ├── redstonePowerRules.ts      # 红石充能规则
│   │   │   └── redstoneGraph.ts           # 信号图引擎
│   │   └── skillRegistry.ts
│   ├── scripts/
│   │   ├── redstone3d/                    # ★ 三维综合管道
│   │   │   ├── yosys_frontend.py          # Verilog→门级网表
│   │   │   ├── cell_library.py            # MCHPRS 标准单元库
│   │   │   ├── placer.py                  # 三维布局器
│   │   │   ├── maze_router.py             # Lee 迷宫布线器
│   │   │   ├── synth.py                   # 综合主管道
│   │   │   ├── mchprs_sim.py              # MCHPRS 注入式仿真
│   │   │   ├── regress.py                 # 分层验证
│   │   │   ├── verify_alu8.py             # ALU 验证
│   │   │   ├── redstone.lib               # 标准单元 liberty 文件
│   │   │   └── BUG_nucleation_edges.md    # 调研：非 bug
│   │   ├── riscv_compiler.py              # RISC-V→红石编译器
│   │   ├── hdl_compiler.py                # HDL→红石编译器
│   │   ├── nucleation_bridge.py           # Nucleation 仿真桥接
│   │   ├── build_riscv_tiny.cjs           # RISC-V Tiny 建造脚本
│   │   ├── build_riscv_multibot.cjs       # 多 Bot 协同建造
│   │   ├── build_fib_v1.cjs               # Fibonacci 计算机
│   │   ├── build_dikc4_v3.cjs             # DIKC-4 CPU
│   │   ├── build_display_*.cjs            # 显示屏系列
│   │   └── cpu_simulator.py               # CPU 行为仿真
│   ├── dist/
│   ├── package.json
│   └── tsconfig.json
└── README.md
```

## 建造约束（游戏实测）

| 规则 | 说明 |
|------|------|
| `GLASS_BASE` | 玻璃基底隔离，超平坦世界草地全局导电 |
| `CMD_RATE_LIMIT` | bot.chat 命令 >150ms/条被丢弃（实测：200ms=100%，80ms=14%） |
| `SETBLOCK_LOAD_RADIUS` | Bot 距目标>210 格 /setblock 静默失败（实测：240格=0/10） |
| `NO_COORD_OVERLAP` | 多门布局坐标不可重叠 |
| `CMD_DELAY` | 命令间最小 200ms 延迟 |
| `BUILD_ORDER` | Y-1 基底 → Y 石块 → Y+1 火把 |
| `FANOUT_FROM_WIRE` | 扇出分叉必须从 wire 而非 pin（repeater 不横向导通） |
| `DIAGONAL_RAMP_SHORT` | 红石线对角斜连：不同 net 对向位置短路 |
| `NO_FLOATING_DUST` | 悬空红石线（下方无实心块）令 MCHPRS 异常 |
| `DUST_DENSITY_ON2` | 密集红石粉图边数 O(N²)，布线越密仿真越慢 |

## MC-31100 修复（Forge Mod）

`mods/` 提供 Forge 1.20.1 和 1.21.4 两个版本的 Mixin mod，修复 `/setblock` 放置红石元件不激活的原生 bug。源码用 Java（Mixin + @Inject + @Invoker），编译后放入 mods 文件夹使用。

## 依赖与致谢

| 项目 | 协议 | 用途 |
|------|------|------|
| [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) | MIT | MCP 基础框架 |
| [Mineflayer](https://github.com/PrismarineJS/mineflayer) | MIT | Minecraft Bot API |
| [Nucleation](https://github.com/Schem-at/Nucleation) | MIT | 红石仿真引擎 |
| [Yosys](https://github.com/YosysHQ/yosys) | ISC | Verilog 逻辑综合 |
| [ujjwal-2001/RISCV_8bit_pipeline](https://github.com/ujjwal-2001/RISCV_8bit_pipeline) | - | RISC-V 8-bit 5 级流水线参考 |
| [qmn/dewey](https://github.com/qmn/dewey) | BSD-2 | PERSHING 红石 P&R 算法参考 |
| [Mineflayer 生态](https://github.com/PrismarineJS) | MIT | 寻路/PVP/自动工具 |

## 协议

- 源代码：MIT
- SKILL.md 知识文档：CC-BY-4.0
- Nucleation 组件继承上游 MIT
- Forge mod：MIT

## 已知限制

- 整体布线（rip-up）>100 门偏慢（分钟级），大电路用分层验证免整体仿真
- 密集红石粉有 O(N²) 图边（dust 全互连的固有语义），整体 MCHPRS 仿真需控制 dust 密度
- 建造需 Minecraft 开启作弊（`/setblock` 需 OP）
- 仅支持 Minecraft Java 版 1.20.1+，LAN 连接
- `set_lever_power`/`set_signal_strength` 等运行时 API 在当前 nucleation 绑定中不驱动网络，需用 redstone_block 注入

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
