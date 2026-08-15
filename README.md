# Minecraft Redstone MCP — 红石电路设计、仿真与游戏内建造系统

基于 [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) 的扩展，提供红石电路的结构化设计、MCHPRS 物理仿真验证和游戏内自动建造能力。已验证的最大成果：**23 门 alu1（AND/OR/XOR/SUB 五操作 ALU）完整布线，MCHPRS 40 向量全对，游戏内 /setblock 实建后真值表 40/40 通过**。

## 架构

```
Verilog → yosys 综合 → 门级网表 → 拓扑布局 → 3D 协商式布线（PathFinder3D）
                                    ↓
                           nucleation MCHPRS 物理仿真（真值表）
                                    ↓
                     export_solution → bot /setblock 实建 → 游戏内真值表
```

**核心管道**：源代码 → 提取单元 → 红石重建 → 模拟验证 → 游戏内建造。同一份布线结果同时用于 MCHPRS 仿真与游戏实建，保证"验证的就是建造的"。

## 三层能力体系

### 1. 知识层（docs/SKILL.md）
- 红石元件速查表与红石时序常量
- 结构化电路编码格式（JSON schema，含真值表/时序）
- 标准电路目录（NOT/AND/OR/XOR/RS锁存/T触发器/全加器等）
- **建造约束与实测规则**：基底隔离、门间隔离、/setblock 命令速率与顺序、MCHPRS 仿真规则、区块加载约束、三维布线实测规则（via 塔、楼梯斜降、中继器刷新）

### 2. 仿真层（nucleation MCHPRS + 行为级 + 分层验证）
| 仿真方式 | 用途 | 规模上限 |
|---------|------|---------|
| MCHPRS 块级真红石仿真 | 单门/小电路物理验证（6 标准单元各 4/4） | ≤ 几门 |
| MCHPRS 整体仿真 | 整模块真值表（alu1 40 向量） | 数千块 |
| 行为级逻辑仿真 | netlist 功能验证（组合逻辑精确） | 无上限 |

### 3. 执行层
| 方式 | 适用场景 |
|------|---------|
| Mineflayer Bot + /setblock | 已验证可建整块 alu1（3.3 万块，多 bot 持载区块 + 150ms 命令间隔） |
| litematic 导出 | 任意规模一次性粘贴 |
| Minecraft Forge mod (1.20.1/1.21.4) | 修复 MC-31100（/setblock 红石元件不激活） |

## 验证结果

### alu1（23 门，AND/OR/XOR/SUB）— 2026-08-15
| 验证 | 结果 |
|------|------|
| 布线收敛（29/29 网，0 短路，0 缺网） | ✅ 2 层 83 秒 |
| MCHPRS 40 向量真值表（y + cout） | **40/40** ✅ |
| 游戏内 /setblock 实建 + 40 向量真值表 | **40/40** ✅ |

### 更早验证
| 电路 | 测试结果 |
|------|---------|
| 6 门标准单元（NOT/BUF/OR/AND/NAND/NOR） | 各 4/4 ✅ |
| 全加器（物理+逻辑分层验证） | 8/8 ✅ |
| 8-bit ALU（160 门，行为仿真） | 80/80 ✅ |
| RISC-V 5 级流水线全配置（6226 门，行为仿真） | 12/12 ✅ |
| 游戏内单门（NOT/AND/NAND）与 3-bit 进位计算器 | 各 4/4 ✅ |

## 快速开始

```bash
cd mcp-server && npm install && npm run build
pip install nucleation
brew install yosys   # 可选（Verilog 综合）
```

MCP 配置 `claude_desktop_config.json`：
```json
{ "mcpServers": { "minecraft": { "command": "node", "args": ["/path/to/mcp-server/dist/mcp-server.js"] } } }
```

## redstone3d 包（三维大规模综合）

`mcp-server/scripts/redstone3d/` 提供完整的三维电路综合管道：

```
yosys_frontend.py  → Verilog → 门级网表（netlists.json）
cell_library.py    → 标准单元库（6 门，MCHPRS 全验证，target 输出级防反向驱动）
placer.py          → 拓扑分层三维布局（西进东出数据流，体素防重叠）
pathfinder3d.py    → PathFinder3D 协商式布线（动态层数、via 塔、功率感知馈入检查）
refresh3d.py       → 流感知中继器插入 + 功率模拟（上层长线不再衰减）
route_buildable.py → placements → BuildResult（wires/repeaters/supports）
build_from_route.py→ 统一发射器：MCHPRS 仿真与游戏实建共用
validate.py        → 40 向量真值表 + 模型-现实一致性对比
export_solution.py → 布局 → bot 建造 JSON（含悬空支撑审计）
diag_loaded.py     → 免重布线的门级电气诊断
fix_floaters.py    → 悬空线局部绕行修补
```

`riscv_build/` 提供游戏内建造与批量验证：

```
build_alu1.cjs     → bot 实建 + 40 向量真值表（多 bot 持载区块）
build_verify.cjs   → 通用 bot 建造/验证器
export_blocks.py   → 模块 → 建造 JSON
run_one_config.py  → 单配置路由+仿真（Win 批量单元，断线续跑）
batch_launcher.py  → 多配置并行批量（独立进程，免进程池崩溃）
```

## 建造约束（游戏实测）

| 规则 | 说明 |
|------|------|
| `GLASS_BASE` | 玻璃基底隔离，超平坦世界草地全局导电 |
| `CMD_RATE_LIMIT` | bot.chat 命令 >150ms/条安全（实测 60ms 丢 ~1% 块、150ms 可靠） |
| `SETBLOCK_LOAD_RADIUS` | Bot 距目标 >13 区块 /setblock 静默失败 |
| `NO_COORD_OVERLAP` | 多门布局坐标不可重叠 |
| `BUILD_ORDER` | 基底 → 石块 → 火把 → 灰（支撑先行） |
| `NO_FLOATING_DUST` | 非方块类元件不可悬空——游戏内会掉落（MCHPRS 容忍但游戏不） |
| `DROP_STONE_SUPPORT` | 楼梯斜降起点的灰必须在可充能方块上（玻璃断开斜降：实测 glass=0 / stone=14） |
| `REFRESH_FLOW` | 上层长线必须流感知插入刷新中继器（每 ≤10 格），否则衰减到 0 |
| `SETTLE_TIME` | 深链（30+ 中继器）稳定 ≥5s，游戏内测试建议 10s |
| `CHUNK_HOLDERS` | 超单玩家视界的电路需多个持载 bot；mineflayer 只读本 bot 视界 |

## MC-31100 修复（Forge Mod）

`mods/` 提供 Forge 1.20.1 和 1.21.4 两个版本的 Mixin mod，修复 `/setblock` 放置红石元件不激活的原生 bug。

## 依赖与致谢

| 项目 | 协议 | 用途 |
|------|------|------|
| [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) | MIT | MCP 基础框架 |
| [Mineflayer](https://github.com/PrismarineJS/mineflayer) | MIT | Minecraft Bot API |
| [Nucleation](https://github.com/Schem-at/Nucleation) | MIT | 红石仿真引擎 |
| [Yosys](https://github.com/YosysHQ/yosys) | ISC | Verilog 逻辑综合 |
| [ujjwal-2001/RISCV_8bit_pipeline](https://github.com/ujjwal-2001/RISCV_8bit_pipeline) | - | RISC-V 8-bit 5 级流水线参考 |
| [qmn/dewey](https://github.com/qmn/dewey) | BSD-2 | PERSHING 红石 P&R 算法参考 |

## 协议

- 源代码：MIT
- SKILL.md 知识文档：CC-BY-4.0
- Nucleation 组件继承上游 MIT
- Forge mod：MIT

## 已知限制

- 整体布线（协商式 rip-up）对百门以上电路偏慢；大电路用分层验证或行为仿真先行
- 密集红石粉有 O(N²) 图边，整体 MCHPRS 仿真需控制 dust 密度
- 建造需 Minecraft 开启作弊（`/setblock` 需 OP），Java 版 1.20.1+，LAN 或同机连接
- MCHPRS 容忍悬空元件而游戏会掉落——导出前必须过支撑审计
