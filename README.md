# Minecraft Redstone MCP — AI 驱动的红石电路设计、仿真与建造系统

基于 [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) 的扩展，为 AI Agent 添加红石电路的结构化设计、仿真验证和游戏内自动建造能力。

## 架构

```
用户自然语言 → Agent (Claude) → MCP Server → Mineflayer Bot → Minecraft
                   ↑                              ↑
              SKILL.md (知识)            Nucleation (仿真引擎)
```

**三层协作**：
1. **知识层**（SKILL.md）：Agent 读取电路分类、编码格式、建造约束
2. **仿真层**（nucleation_bridge.py）：建造前逻辑验证，9/9 电路通过
3. **执行层**（buildRedstoneCircuit.ts）：游戏内自动放置 `/setblock` 命令

## 游戏内验证结果（2026-07-25）

| 电路 | 测试结果 |
|------|---------|
| NOT Gate | 2/2 ✅ |
| AND Gate | 4/4 ✅ |
| NAND Gate (AND→NOT chain) | 4/4 ✅ |
| 3-bit 进位计算器 | 4/4 ✅ |

## 快速开始

### 1. 安装依赖

```bash
cd mcp-server
npm install
npm run build
pip install nucleation
```

### 2. 配置 Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "minecraft": {
      "command": "node",
      "args": ["/path/to/mcp-server/dist/mcp-server.js"]
    }
  }
}
```

### 3. 使用

1. 打开 Minecraft Java 1.20.1+，进入世界，对局域网开放
2. 重启 Claude Desktop
3. 对话示例：
   - "加入游戏，端口 25565"
   - "在脚下建一个 AND 门"
   - "仿真验证 XOR 门"

## MCP 工具

| 工具 | 功能 |
|------|------|
| `joinGame` | Bot 加入游戏 |
| `leaveGame` | Bot 退出 |
| `buildRedstoneCircuit` | 建造标准红石电路（16 个模板） |
| `simulateRedstoneCircuit` | 仿真验证电路正确性 |
| `scanRedstoneCircuit` | 扫描已有电路，识别元件和模式 |
| `diffRedstoneCircuit` | 计算两个电路模板的差异 |

## 文件结构

```
mcp-server/
├── src/
│   ├── skills/verified/
│   │   ├── buildRedstoneCircuit.ts    # 建造工具
│   │   ├── simulateRedstoneCircuit.ts # 仿真工具
│   │   ├── scanRedstoneCircuit.ts     # 扫描工具
│   │   └── diffRedstoneCircuit.ts     # 差异工具
│   ├── lib/
│   │   ├── terrainDetector.ts         # 地形检测
│   │   ├── redstonePowerRules.ts      # 红石充能规则
│   │   └── redstoneGraph.ts           # 信号图引擎
│   └── skillRegistry.ts              # 工具注册
├── scripts/
│   ├── nucleation_bridge.py           # Nucleation 仿真桥接
│   ├── build-2bit-adder.cjs          # 2-bit 加法器建造脚本
│   └── test-2bit-adder.cjs           # 2-bit 加法器测试脚本
├── dist/                              # 编译输出
└── package.json
```

Agent Skill 文件位于 `~/.claude/skills/minecraft-redstone-coding/SKILL.md`（~1050 行）。

## 建造约束（游戏中验证发现）

| 规则 | 说明 |
|------|------|
| 玻璃基底 | 超平坦世界草地全局导电，必须用玻璃隔离 |
| 线不覆盖安装石 | 门间连线 `< mountPos`，否则墙上火把掉落 |
| 命令延迟 ≥200ms | 更快会导致服务器丢弃命令 |
| 红石块必须同Y层 | 红石块只能充能同 Y 层紧邻灰线 |
| 电路距 Bot ≤50 格 | `blockAt()` 在未加载区块返回 null |

## 依赖与致谢

本项目基于以下开源项目构建：

| 项目 | 协议 | 用途 |
|------|------|------|
| [FundamentalLabs/minecraft-mcp](https://github.com/FundamentalLabs/minecraft-mcp) | MIT | MCP Server 基础框架，30 个已验证技能 |
| [Mineflayer](https://github.com/PrismarineJS/mineflayer) | MIT | Minecraft Bot API（Java 版） |
| [mineflayer-pathfinder](https://github.com/PrismarineJS/mineflayer-pathfinder) | MIT | A* 寻路 |
| [mineflayer-pvp](https://github.com/PrismarineJS/mineflayer-pvp) | MIT | PVP 战斗 |
| [mineflayer-tool](https://github.com/PrismarineJS/mineflayer-tool) | MIT | 自动工具选择 |
| [mineflayer-collectblock](https://github.com/PrismarineJS/mineflayer-collectblock) | MIT | 方块采集 |
| [@modelcontextprotocol/sdk](https://github.com/modelcontextprotocol/sdk) | MIT | MCP 协议实现 |
| [Nucleation](https://github.com/Schem-at/Nucleation) | AGPL-3.0 | 红石仿真引擎（Schematic + CircuitBuilder + MCHPRS） |
| [Vec3](https://github.com/PrismarineJS/node-vec3) | MIT | 3D 向量运算 |

## 协议

本项目基于 FundamentalLabs/minecraft-mcp（MIT）进行扩展。

- 源代码部分：MIT License
- Nucleation 桥接组件：AGPL-3.0（继承自 Nucleation）
- SKILL.md 知识文档：CC-BY-4.0

详见各子目录的 LICENSE 文件。

## 已知限制

- 多火把组合电路（XOR/HalfAdder/FullAdder）的手工块级布局未完全验证——需 Nucleation MCHPRS 块级仿真支持（Phase 3）
- 建造需 Minecraft 开启作弊（`/setblock` 需要 OP 权限）
- Bot 通过 LAN 加入，需同一网络
- 仅支持 Minecraft Java 版 1.20.1+

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
