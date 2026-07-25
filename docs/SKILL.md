---
name: minecraft-redstone-coding
description: Use when the agent needs to design, describe, simulate, or generate Minecraft redstone circuits — including logic gates (NOT/OR/AND/XOR/NAND/NOR/XNOR), sequential circuits (RS NOR latch, T/D flip-flop, pulse limiter), arithmetic (half/full adder, N-bit ripple-carry adder), clocks (repeater/hopper/comparator), and contraptions (piston doors, item sorters, auto-farms). Triggers on "红石电路", "logic gate", "逻辑门", "flip-flop", "触发器", "adder", "加法器", "piston door", "活塞门", "item sorter", "物品分类", "redstone clock", "红石时钟", "redstone circuit", "place redstone", or any request to build functional redstone in Minecraft.
---

# Minecraft 红石电路结构化编码指南

## 概述

本 skill 教 agent 用**结构化 JSON 编码**描述和生成 Minecraft 红石电路。核心原则：

> 每个电路 = 原点坐标 `(bx,by,bz)` + 相对偏移的逐块布局 + 真值表 → 可翻译为 `/setblock` 命令序列

本 skill 配套两个 MCP 工具：
- **`simulateRedstoneCircuit`**：建造前在 Nucleation 引擎中仿真验证
- **`buildRedstoneCircuit`**：仿真通过后在游戏中实际建造

完整工作流：
```
需求 → 查找/组合电路模板 → 生成电路 JSON → simulateRedstoneCircuit 仿真
  → 分析结果/修正 → 仿真通过 → buildRedstoneCircuit 建造
```

## 触发条件

- 用户要求建造红石电路、逻辑门、触发器、加法器、活塞门、物品分类器等
- 用户提供真值表要求实现
- 用户要求分析或优化现有红石电路
- 用户询问红石时序问题

**不使用本 skill 的场景**：纯装饰性建筑、非红石方块放置（用 `buildSomething` 替代）

## 红石元件速查表

| 元件 | Block ID | 关键 States | 行为说明 |
|------|----------|------------|---------|
| 红石粉 | `minecraft:redstone_wire` | `power=0-15`, `north/south/east/west=none\|side\|up` | 自动连接相邻元件，信号每格衰减1 |
| 红石中继器 | `minecraft:repeater` | `facing`, `delay=1-4`, `powered` | 单向，信号重置为15，可锁定 |
| 红石比较器 | `minecraft:comparator` | `facing`, `mode=compare\|subtract`, `powered` | 比较/减法模式，读取容器 |
| 红石火把 | `minecraft:redstone_torch` | `lit=true\|false` | 非门(1tick延迟)，附在方块侧面或顶面 |
| 红石块 | `minecraft:redstone_block` | — | 常亮电源，信号强度15 |
| 侦测器 | `minecraft:observer` | `facing`, `powered` | 检测方块更新，输出1tick脉冲 |
| 活塞 | `minecraft:piston` | `facing`, `extended` | 推12方块，不能推基岩/箱等 |
| 粘性活塞 | `minecraft:sticky_piston` | `facing`, `extended` | 推+拉回1方块 |
| 拉杆 | `minecraft:lever` | `facing`, `powered` | 手动开关，信号15 |
| 石按钮 | `minecraft:stone_button` | `facing`, `powered` | 1秒脉冲(20tick) |
| 木按钮 | `minecraft:oak_button` | `facing`, `powered` | 1.5秒脉冲(30tick) |
| 石压力板 | `minecraft:stone_pressure_plate` | `powered` | 仅实体触发 |
| 木压力板 | `minecraft:oak_pressure_plate` | `powered` | 实体+物品触发 |
| 标靶 | `minecraft:target` | `power=0-15` | 三叉戟/箭触发，重定向红石粉 |
| 发射器 | `minecraft:dispenser` | `facing`, `triggered` | 发射物品/箭/药水 |
| 投掷器 | `minecraft:dropper` | `facing`, `triggered` | 投放物品 |
| 漏斗 | `minecraft:hopper` | `facing`, `enabled` | 传输物品，时钟组件(4tick/物品) |
| 音符盒 | `minecraft:note_block` | `powered`, `note=0-24` | 侦测器触发源 |
| 红石灯 | `minecraft:redstone_lamp` | `lit` | 视觉输出 |
| 铁门 | `minecraft:iron_door` | `facing`, `half=lower\|upper`, `open` | 仅红石可开 |
| 铁活板门 | `minecraft:iron_trapdoor` | `facing`, `half`, `open` | 仅红石可开 |
| 栅栏门 | `minecraft:oak_fence_gate` | `facing`, `open`, `powered` | |
| 阳光探测器 | `minecraft:daylight_detector` | `power=0-15`, `inverted` | 白天→信号 |
| TNT | `minecraft:tnt` | `unstable` | 红石引爆 |
| 粘液块 | `minecraft:slime_block` | — | 可被活塞推拉，粘连相邻方块 |
| 蜂蜜块 | `minecraft:honey_block` | — | 类似粘液块但不粘粘液块 |

### 红石时序常量

| 单位 | 时长 | 说明 |
|------|------|------|
| 1 游戏刻 (gt) | 0.05s | 20 TPS |
| 1 红石刻 (rt) | 0.1s = 2gt | 中继器/火把延迟单位 |
| 红石火把 | 1rt 延迟 | 开关均有延迟 |
| 红石中继器 | 1-4rt 可调 | 默认1rt |
| 红石比较器 | 1rt | 固定 |
| 侦测器脉冲 | 1rt | 固定1rt脉冲 |
| 活塞伸缩 | 1.5-2rt | 3-4gt |
| 漏斗传输 | 4rt/物品 | 8gt |

## 建造约束与语法限制（游戏验证，2026-07-25）

以下规则源自游戏内实际建造测试，违反将导致电路失效。

### 基底隔离规则（强制）

**超平坦世界草地全局导连。** 所有红石电路必须在非导电基底上建造。

```
❌ 直接在草地/泥土上放置石块 → 输入信号通过地面传导到所有门，火把全部失效
✅ 玻璃基底延伸至电路边界外 ≥3 格
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `GLASS_BASE` | 所有电路必须在玻璃（或等效非导电方块）上建造 | 信号通过地面导连，火把状态不可预测 |
| `GLASS_MARGIN` | 玻璃基底必须超出电路最大 X/Z 边界 ≥3 格 | 边缘接地泄漏 |
| `Y_ISOLATION` | 电路内所有石块不得与天然地面有任何 Y 层接触 | 超平坦世界全局导电 |

### 门间隔离规则（强制）

**独立门输出必须通过中继器隔离。** 门与门之间的连线不得覆盖安装石块。

```
❌ 线直接连到下一个门的安装石 → 线覆盖了石头，火把掉落
✅ 线停在安装石前一格 (< mountX)，灰→石强充能传递信号
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `WIRE_STOP_BEFORE_MOUNT` | 门间连线必须在目标安装石**前一格**停止（`< mountPos`，不 `<=`） | 线覆盖安装石，墙上火把掉落 |
| `REPEATER_ISOLATION` | 建议在门间放中继器（`delay=1`）隔离信号 | 反向馈电，门间干扰 |
| `POWER_TRANSFER` | 灰通过**强充能**传递信号到相邻石块（灰→石，同 Y 层相邻） | 灰不能直接充能 2 格外或对角位置的石块 |

### /setblock 命令约束（强制）

**命令速率和顺序影响电路完整性。**

```
❌ 大批量 /setblock 无延迟 → 服务器丢弃命令
❌ /fill 清除 Y 层后再在 Y 层放置方块 → 地面被清，灰无支撑
✅ 先放所有 Y 层石块（支撑），再放 Y+1 火把和灰
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `CMD_DELAY` | `/setblock` 命令间最小延迟 200ms | 命令被服务器静默丢弃 |
| `BUILD_ORDER` | 电路建造顺序：Y-1 基底 → Y 层石块 → Y 层输入灰 → Y+1 火把 → Y+1 灰 → Y 层墙上火把 → Y 层输出灰 | 后续方块无支撑而掉落 |
| `NO_FILL_Y` | 不得 `/fill` 清除 Y 层（地面层）——只能清除 Y+1 及以上 | 输入灰和安装石被摧毁，火把无支撑 |
| `NO_DESTROY_INPUTS` | 测试输入时使用 `redstone_block`/`air`（不带 `destroy`），不得用 `air destroy` | `destroy` 模式可能摧毁相邻电路方块 |

### 区块加载约束（强制）

**Bot 只能读取已加载区块内的方块状态。**

```
❌ 在 X=200 处放置方块，Bot 在 X=0 处读取 → 返回 null
✅ 电路建造在 Bot 50 格范围内
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `CHUNK_RADIUS` | 电路必须建造在 Bot 当前位置 50 格范围内 | `bot.blockAt()` 返回 `null` |
| `BUILD_NEAR_BOT` | 建造脚本使用 `Math.floor(bot.entity.position.x) + offset` 定位 | 块在未加载区块中不可读 |

### 已验证门模板

以下模板经过游戏内 4/4 全组合测试验证，可直接使用：

| 门 | 验证结果 | 关键特征 |
|----|---------|---------|
| **NOT** | 2/2 ✅ | 1 地面火把 + 1 石块 + 2 灰 |
| **AND** | 4/4 ✅ | 3 地面火把 + 1 墙上火把输出，灰在安装块顶上 |
| **NAND** | 4/4 ✅ | AND + 墙上火把 NOT（门链验证通过） |

### 未验证门模板

以下模板的逻辑正确性已由仿真引擎验证，但块级布局未经游戏内测试：

| 门 | 仿真 | 游戏内 | 阻塞原因 |
|----|------|--------|---------|
| **XOR** | ✅ | ❌ | 需 2×AND + NOT + OR 组合，门间线互连复杂 |
| **Half Adder** | ✅ | ❌ | XOR + AND 组合，Y+1 级灰路由与 OR 线冲突 |
| **Full Adder** | ✅ | ❌ | HA 链 + 进位桥，规模超出单脚本可靠建造 |
| **Ripple-Carry Adder** | ✅ | ❌ | 同上 |

> **核心结论**：单门和门链（≤4 个火把，≤2 级深度）可手写逐块坐标验证。复杂多门组合（XOR/HA/FA）的手工布线不可靠——需要通过 **Nucleation + MCHPRS 块级仿真引擎**生成和验证完整块布局后再建造。

## 电路编码格式规范

所有电路使用统一 JSON 描述。格式：

```json
{
  "name": "电路名",
  "category": "logic_gate | sequential | arithmetic | signal | contraption",
  "dimensions": { "width": 3, "height": 2, "depth": 3 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [4, 0, 1], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "Q": 0 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" }
  ],
  "propagation_delay_ticks": 2,
  "notes": "标准AND门，使用3个火把实现"
}
```

### 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 电路名称 |
| `category` | enum | ✅ | 分类 |
| `dimensions` | object | ✅ | `width(X) × height(Y) × depth(Z)` |
| `inputs` | array | ✅ | 输入端口，含 label/pos/direction |
| `outputs` | array | ✅ | 输出端口，含 label/pos/direction |
| `truth_table` | array | ✅ | 输入组合→预期输出，用于自动仿真验证 |
| `blocks` | array | ✅ | 逐块布局，pos 为相对原点偏移 `[dx, dy, dz]` |
| `propagation_delay_ticks` | number | 推荐 | 从输入变化到输出稳定的最大延迟(rt) |
| `notes` | string | 推荐 | 实现说明 |
| `params` | object | 可选 | 参数化电路的可变参数（如 `bits`） |

### 坐标约定

- `pos: [dx, dy, dz]` = 相对电路原点 `(bx, by, bz)` 的偏移
  - `dx`：X轴（东西），增量为东
  - `dy`：Y轴（上下），增量向上
  - `dz`：Z轴（南北），增量为南
- 原点 `(0,0,0)` = 电路输入侧左下角
- 默认朝向：输入从**西（-X）**进入，输出向**东（+X）**输出
- `block` 字段格式：`minecraft:block_id` 或 `minecraft:block_id[key1=val1,key2=val2]`
- `role` 字段标记 block 的逻辑角色：
  - `input`：输入端口
  - `output`：输出端口
  - `power`：电源（红石块、拉杆等）
  - `wire`：信号传输线
  - `inverter`：非门（红石火把）
  - `repeater`：中继器/延迟
  - `comparator`：比较器
  - `mount`：安装面（固体方块用于放置火把等）
  - `piston`：活塞/粘性活塞
  - `container`：容器（漏斗、箱子等）
  - `structure`：结构方块（纯建筑用途）
  - `ground`：地线/参考面

---

## 电路目录

### 1. 逻辑门

#### 1.1 NOT Gate（非门）

| 输入 A | 输出 Q |
|--------|--------|
| 0 | 1 |
| 1 | 0 |

```json
{
  "name": "NOT Gate",
  "category": "logic_gate",
  "dimensions": { "width": 3, "height": 2, "depth": 1 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [2, 0, 0], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "Q": 1 },
    { "A": 1, "Q": 0 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 1,
  "notes": "最简非门。火把附在方块上，方块被充能时火把熄灭(输出0)，方块未充能时火把点亮(输出1)。火把有1rt开关延迟。"
}
```

**JavaScript 代码模板：**
```javascript
// NOT Gate at (bx, by, bz)
function notGate(bx, by, bz) {
    setBlock(bx,     by,   bz, 'minecraft:redstone_wire');           // input
    setBlock(bx + 1, by,   bz, 'minecraft:stone');                   // mount
    setBlock(bx + 1, by+1, bz, 'minecraft:redstone_torch[lit=true]'); // torch
    setBlock(bx + 2, by,   bz, 'minecraft:redstone_wire');           // output
}
```

#### 1.2 OR Gate（或门）

| A | B | Q |
|---|---|----|
| 0 | 0 | 0 |
| 0 | 1 | 1 |
| 1 | 0 | 1 |
| 1 | 1 | 1 |

```json
{
  "name": "OR Gate",
  "category": "logic_gate",
  "dimensions": { "width": 2, "height": 1, "depth": 3 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" },
    { "label": "B", "pos": [0, 0, 2], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [1, 0, 1], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "Q": 0 },
    { "A": 0, "B": 1, "Q": 1 },
    { "A": 1, "B": 0, "Q": 1 },
    { "A": 1, "B": 1, "Q": 1 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [1, 0, 1], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 0,
  "notes": "最简单的门——仅红石粉连接。任意输入为1则输出为1。无延迟。但信号会衰减，长距离需加中继器。"
}
```

**JavaScript 代码模板：**
```javascript
function orGate(bx, by, bz) {
    setBlock(bx,     by, bz,     'minecraft:redstone_wire');  // input A
    setBlock(bx,     by, bz + 2, 'minecraft:redstone_wire');  // input B
    setBlock(bx,     by, bz + 1, 'minecraft:redstone_wire');  // junction
    setBlock(bx + 1, by, bz + 1, 'minecraft:redstone_wire');  // output Q
}
```

#### 1.3 AND Gate（与门）

| A | B | Q |
|---|---|----|
| 0 | 0 | 0 |
| 0 | 1 | 0 |
| 1 | 0 | 0 |
| 1 | 1 | 1 |

```json
{
  "name": "AND Gate",
  "category": "logic_gate",
  "dimensions": { "width": 5, "height": 2, "depth": 3 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" },
    { "label": "B", "pos": [0, 0, 2], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [4, 0, 1], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "Q": 0 },
    { "A": 0, "B": 1, "Q": 0 },
    { "A": 1, "B": 0, "Q": 0 },
    { "A": 1, "B": 1, "Q": 1 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [3, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [3, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [4, 0, 1], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 2,
  "notes": "AND = NOT(OR(NOT(A), NOT(B)))。使用3个火把的德摩根实现。每个输入经过NOT→OR合并→NOT。2rt延迟。"
}
```

**JavaScript 代码模板：**
```javascript
function andGate(bx, by, bz) {
    // Inputs
    setBlock(bx,     by,   bz,     'minecraft:redstone_wire');           // A
    setBlock(bx,     by,   bz + 2, 'minecraft:redstone_wire');           // B
    // NOT A
    setBlock(bx + 1, by,   bz,     'minecraft:stone');                   // mount
    setBlock(bx + 1, by+1, bz,     'minecraft:redstone_torch[lit=true]');// torch NOT A
    // NOT B
    setBlock(bx + 1, by,   bz + 2, 'minecraft:stone');                   // mount
    setBlock(bx + 1, by+1, bz + 2, 'minecraft:redstone_torch[lit=true]');// torch NOT B
    // OR junction
    setBlock(bx + 2, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz + 2, 'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz + 1, 'minecraft:redstone_wire');
    // Final NOT
    setBlock(bx + 3, by,   bz + 1, 'minecraft:stone');
    setBlock(bx + 3, by+1, bz + 1, 'minecraft:redstone_torch[lit=true]');
    // Output
    setBlock(bx + 4, by,   bz + 1, 'minecraft:redstone_wire');           // Q
}
```

#### 1.4 XOR Gate（异或门）

| A | B | Q |
|---|---|----|
| 0 | 0 | 0 |
| 0 | 1 | 1 |
| 1 | 0 | 1 |
| 1 | 1 | 0 |

```json
{
  "name": "XOR Gate",
  "category": "logic_gate",
  "dimensions": { "width": 5, "height": 2, "depth": 3 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" },
    { "label": "B", "pos": [0, 0, 2], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [4, 0, 1], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "Q": 0 },
    { "A": 0, "B": 1, "Q": 1 },
    { "A": 1, "B": 0, "Q": 1 },
    { "A": 1, "B": 1, "Q": 0 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [2, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [3, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [3, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [4, 0, 1], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 2,
  "notes": "XOR = (A OR B) AND NOT(A AND B) 的火把实现。4个火把。2rt延迟。更紧凑的替代方案：比较器减法模式(1rt, 2×3×2)。"
}
```

**JavaScript 代码模板：**
```javascript
function xorGate(bx, by, bz) {
    // Inputs
    setBlock(bx,     by,   bz,     'minecraft:redstone_wire');
    setBlock(bx,     by,   bz + 2, 'minecraft:redstone_wire');
    // NOT A, NOT B
    setBlock(bx + 1, by,   bz,     'minecraft:stone');
    setBlock(bx + 1, by+1, bz,     'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 1, by,   bz + 2, 'minecraft:stone');
    setBlock(bx + 1, by+1, bz + 2, 'minecraft:redstone_torch[lit=true]');
    // Wires to junction
    setBlock(bx + 2, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz + 2, 'minecraft:redstone_wire');
    // Middle torch + second torch
    setBlock(bx + 2, by,   bz + 1, 'minecraft:stone');
    setBlock(bx + 2, by+1, bz + 1, 'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 3, by,   bz + 1, 'minecraft:stone');
    setBlock(bx + 3, by+1, bz + 1, 'minecraft:redstone_torch[lit=true]');
    // Output
    setBlock(bx + 4, by,   bz + 1, 'minecraft:redstone_wire');
}
```

#### 1.5 NAND/NOR/XNOR

**NAND** = AND + NOT（4火把，3rt延迟）：在 AND 输出端加一个 NOT gate。

**NOR** = OR + NOT（1火把，1rt延迟）：OR 输出端接一个 NOT gate。

**XNOR** = XOR + NOT（5火把，3rt延迟）：在 XOR 输出端加一个 NOT gate。

使用 `compose` 方式实现：先建基础门，在中继器后接 NOT。详见组合规则章节。

---

### 2. 时序/存储电路

#### 2.1 RS NOR Latch（RS NOR 锁存器）

基本的 1-bit 存储单元。两个交叉耦合的 NOR gate。

| S | R | Q | Q' | 状态 |
|---|---|----|----|------|
| 0 | 0 | Q | Q' | 保持 |
| 1 | 0 | 1 | 0  | 置位 |
| 0 | 1 | 0 | 1  | 复位 |
| 1 | 1 | 0 | 0  | 无效(禁止) |

```json
{
  "name": "RS NOR Latch",
  "category": "sequential",
  "dimensions": { "width": 4, "height": 2, "depth": 3 },
  "inputs": [
    { "label": "S", "pos": [0, 0, 0], "direction": "west" },
    { "label": "R", "pos": [0, 0, 2], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [3, 0, 0], "direction": "east" },
    { "label": "Q_bar", "pos": [3, 0, 2], "direction": "east" }
  ],
  "truth_table": [
    { "S": 0, "R": 0, "Q": "hold" },
    { "S": 1, "R": 0, "Q": 1, "Q_bar": 0 },
    { "S": 0, "R": 1, "Q": 0, "Q_bar": 1 },
    { "S": 1, "R": 1, "Q": 0, "Q_bar": 0 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 2], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [1, 0, 2], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 2], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [3, 0, 0], "block": "minecraft:redstone_wire", "role": "output" },
    { "pos": [3, 0, 2], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 2,
  "notes": "两个交叉耦合的 NOR gate。S=1 使 Q=1，R=1 使 Q=0。S=R=1 应永远避免。需要 Stateful 仿真模式。"
}
```

**JavaScript 代码模板：**
```javascript
function rsNorLatch(bx, by, bz) {
    // Inputs S, R
    setBlock(bx,     by,   bz,     'minecraft:redstone_wire');
    setBlock(bx,     by,   bz + 2, 'minecraft:redstone_wire');
    // NOR gates: mount + torch
    setBlock(bx + 1, by,   bz,     'minecraft:stone');
    setBlock(bx + 1, by+1, bz,     'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 1, by,   bz + 2, 'minecraft:stone');
    setBlock(bx + 1, by+1, bz + 2, 'minecraft:redstone_torch[lit=true]');
    // Cross-coupling wires
    setBlock(bx + 2, by,   bz + 1, 'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz + 2, 'minecraft:redstone_wire');
    // Outputs Q, Q_bar
    setBlock(bx + 3, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 3, by,   bz + 2, 'minecraft:redstone_wire');
}
```

#### 2.2 T Flip-Flop（T 触发器）

| T | Q(next) |
|---|---------|
| 0 | Q(保持) |
| 上升沿 | 翻转 |

```json
{
  "name": "T Flip-Flop",
  "category": "sequential",
  "dimensions": { "width": 3, "height": 3, "depth": 3 },
  "inputs": [
    { "label": "T", "pos": [0, 0, 1], "direction": "west" }
  ],
  "outputs": [
    { "label": "Q", "pos": [2, 0, 0], "direction": "east" }
  ],
  "truth_table": [
    { "T": 0, "Q": "hold" },
    { "T": "rising", "Q": "toggle" }
  ],
  "blocks": [
    { "pos": [0, 0, 1], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [0, 0, 0], "block": "minecraft:dropper[facing=up]", "role": "container" },
    { "pos": [0, 1, 0], "block": "minecraft:hopper[facing=down]", "role": "container" },
    { "pos": [1, 0, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [1, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [1, 2, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [1, 2, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 2, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 0], "block": "minecraft:stone", "role": "mount" },
    { "pos": [2, 1, 0], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 3,
  "notes": "投掷器-漏斗 T 触发器。最可靠设计。漏斗中放1个物品，每个输入脉冲使物品在漏斗和投掷器间移动一次。需要 Stateful 仿真。"
}
```

#### 2.3 Edge Detector（边沿检测器）

上升沿检测器+脉冲限制器。

| 输入变化 | 输出 |
|---------|------|
| 0→1 (上升沿) | 1rt 脉冲 |
| 1→0 (下降沿) | 无输出 |
| 稳态 | 0 |

```json
{
  "name": "Rising Edge Detector",
  "category": "sequential",
  "dimensions": { "width": 3, "height": 1, "depth": 1 },
  "inputs": [
    { "label": "IN", "pos": [0, 0, 0], "direction": "west" }
  ],
  "outputs": [
    { "label": "PULSE", "pos": [2, 0, 0], "direction": "east" }
  ],
  "truth_table": [
    { "IN": "steady_0", "PULSE": 0 },
    { "IN": "rising", "PULSE": "1rt_pulse" },
    { "IN": "steady_1", "PULSE": 0 },
    { "IN": "falling", "PULSE": 0 }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:observer[facing=west]", "role": "inverter" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 1,
  "notes": "简单上升沿检测器：侦测器面朝输入线。输入从0变1时方块变化被侦测，输出1rt脉冲。下降沿检测器：侦测器面朝NOT门输出。"
}
```

---

### 3. 算术电路

#### 3.1 Half Adder（半加器）

| A | B | S(和) | C(进位) |
|---|---|--------|---------|
| 0 | 0 | 0 | 0 |
| 0 | 1 | 1 | 0 |
| 1 | 0 | 1 | 0 |
| 1 | 1 | 0 | 1 |

```json
{
  "name": "Half Adder",
  "category": "arithmetic",
  "dimensions": { "width": 7, "height": 2, "depth": 4 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" },
    { "label": "B", "pos": [0, 0, 2], "direction": "west" }
  ],
  "outputs": [
    { "label": "S", "pos": [5, 0, 0], "direction": "east" },
    { "label": "C", "pos": [5, 0, 2], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "S": 0, "C": 0 },
    { "A": 0, "B": 1, "S": 1, "C": 0 },
    { "A": 1, "B": 0, "S": 1, "C": 0 },
    { "A": 1, "B": 1, "S": 0, "C": 1 }
  ],
  "blocks": [],
  "propagation_delay_ticks": 3,
  "notes": "由 XOR(产生S) + AND(产生C) 组成。使用 compose 方式实现——将 XOR 和 AND 并排放置，输入线分叉到两个子电路。电路 blocks 通过 compose 动态展开。"
}
```

**JavaScript 代码模板（组合方式）：**
```javascript
function halfAdder(bx, by, bz) {
    // Inputs: split A,B to both XOR and AND
    setBlock(bx,     by,   bz,     'minecraft:redstone_wire');
    setBlock(bx,     by,   bz + 2, 'minecraft:redstone_wire');
    // Splitter bridges
    setBlock(bx + 1, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 1, by,   bz + 1, 'minecraft:stone');
    setBlock(bx + 1, by+1, bz + 1, 'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 2, by,   bz,     'minecraft:stone');
    setBlock(bx + 2, by+1, bz,     'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 3, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 3, by,   bz + 1, 'minecraft:stone');
    setBlock(bx + 3, by+1, bz + 1, 'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 4, by,   bz,     'minecraft:redstone_wire');
    setBlock(bx + 2, by,   bz + 2, 'minecraft:stone');
    setBlock(bx + 2, by+1, bz + 2, 'minecraft:redstone_torch[lit=true]');
    setBlock(bx + 3, by,   bz + 2, 'minecraft:redstone_wire');
    setBlock(bx + 1, by,   bz + 2, 'minecraft:redstone_wire');
    // Outputs
    setBlock(bx + 5, by,   bz,     'minecraft:redstone_wire');  // S (XOR)
    setBlock(bx + 5, by,   bz + 2, 'minecraft:redstone_wire');  // C (AND)
}
```

#### 3.2 Full Adder（全加器）

| A | B | Cin | S(和) | Cout(进位) |
|---|---|-----|--------|----------|
| 0 | 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 1 | 0 |
| 0 | 1 | 0 | 1 | 0 |
| 0 | 1 | 1 | 0 | 1 |
| 1 | 0 | 0 | 1 | 0 |
| 1 | 0 | 1 | 0 | 1 |
| 1 | 1 | 0 | 0 | 1 |
| 1 | 1 | 1 | 1 | 1 |

```json
{
  "name": "Full Adder",
  "category": "arithmetic",
  "dimensions": { "width": 14, "height": 2, "depth": 6 },
  "inputs": [
    { "label": "A", "pos": [0, 0, 0], "direction": "west" },
    { "label": "B", "pos": [0, 0, 2], "direction": "west" },
    { "label": "Cin", "pos": [0, 0, 4], "direction": "west" }
  ],
  "outputs": [
    { "label": "S", "pos": [13, 0, 1], "direction": "east" },
    { "label": "Cout", "pos": [13, 0, 3], "direction": "east" }
  ],
  "truth_table": [
    { "A": 0, "B": 0, "Cin": 0, "S": 0, "Cout": 0 },
    { "A": 0, "B": 0, "Cin": 1, "S": 1, "Cout": 0 },
    { "A": 0, "B": 1, "Cin": 0, "S": 1, "Cout": 0 },
    { "A": 0, "B": 1, "Cin": 1, "S": 0, "Cout": 1 },
    { "A": 1, "B": 0, "Cin": 0, "S": 1, "Cout": 0 },
    { "A": 1, "B": 0, "Cin": 1, "S": 0, "Cout": 1 },
    { "A": 1, "B": 1, "Cin": 0, "S": 0, "Cout": 1 },
    { "A": 1, "B": 1, "Cin": 1, "S": 1, "Cout": 1 }
  ],
  "blocks": [],
  "propagation_delay_ticks": 6,
  "notes": "由2个 Half Adder + 1个 OR gate 组成。HA1 计算 A+B → S1,C1。HA2 计算 S1+Cin → S,C2。Cout = C1 OR C2。使用 compose 展开。N-bit 行波进位加法器通过串联 N 个 FA 实现。"
}
```

#### 3.3 N-Bit Ripple-Carry Adder（N位行波进位加法器）

参数化电路。参数 `bits` 定义了位数（默认4）。

**JavaScript 代码模板：**
```javascript
function rippleCarryAdder(bx, by, bz, bits = 4) {
    const spacing = 7;  // 每个全加器的X方向间距
    
    for (let i = 0; i < bits; i++) {
        const offsetX = i * spacing;
        // 构建单个全加器
        // ... 全加器逻辑 ...
        
        // 进位连接：当前FA的Cout → 下一个FA的Cin
        if (i < bits - 1) {
            setBlock(bx + offsetX + 5, by, bz + 3,
                     'minecraft:repeater[facing=east,delay=1]');
            setBlock(bx + offsetX + 6, by, bz + 3,
                     'minecraft:redstone_wire');
        }
    }
}
```

---

### 4. 信号处理 / 时钟

#### 4.1 Repeater Clock（中继器时钟）

```json
{
  "name": "Repeater Clock",
  "category": "signal",
  "dimensions": { "width": 3, "height": 1, "depth": 1 },
  "inputs": [
    { "label": "ENABLE", "pos": [0, 0, 0], "direction": "west" }
  ],
  "outputs": [
    { "label": "CLK", "pos": [2, 0, 0], "direction": "east" }
  ],
  "truth_table": [
    { "ENABLE": 0, "CLK": 0 },
    { "ENABLE": 1, "CLK": "oscillating" }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:lever[facing=east]", "role": "input" },
    { "pos": [1, 0, 0], "block": "minecraft:repeater[facing=east,delay=2]", "role": "repeater" },
    { "pos": [1, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 0], "block": "minecraft:repeater[facing=west,delay=2]", "role": "repeater" }
  ],
  "propagation_delay_ticks": 4,
  "notes": "2个中继器环形连接。周期=2×delay。启动：快速放置/破坏任一红石粉触发。停止：破坏拉杆或中继器。"
}
```

#### 4.2 Hopper Clock（漏斗时钟）

```json
{
  "name": "Hopper Clock",
  "category": "signal",
  "dimensions": { "width": 4, "height": 2, "depth": 2 },
  "inputs": [],
  "outputs": [
    { "label": "CLK", "pos": [3, 0, 1], "direction": "east" }
  ],
  "truth_table": [
    { "items": 0, "CLK": "stopped" },
    { "items": 16, "CLK": "period_12.8s" }
  ],
  "blocks": [
    { "pos": [0, 0, 0], "block": "minecraft:hopper[facing=east]", "role": "container" },
    { "pos": [1, 0, 0], "block": "minecraft:hopper[facing=west]", "role": "container" },
    { "pos": [1, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [3, 0, 1], "block": "minecraft:redstone_wire", "role": "output" }
  ],
  "propagation_delay_ticks": 0,
  "notes": "最稳定可靠的时钟。周期=物品数量×0.4秒/物品×2(双向)。例如32个物品→25.6秒周期。比较器在漏斗侧读取填充度。"
}
```

---

### 5. 常用装置

#### 5.1 2×2 Piston Door（2×2 活塞门）

```json
{
  "name": "2×2 Piston Door",
  "category": "contraption",
  "dimensions": { "width": 6, "height": 4, "depth": 4 },
  "inputs": [
    { "label": "OPEN", "pos": [0, 0, 1], "direction": "west" }
  ],
  "outputs": [],
  "truth_table": [],
  "blocks": [
    { "pos": [0, 0, 1], "block": "minecraft:redstone_wire", "role": "input" },
    { "pos": [1, 0, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [1, 1, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 0, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 0, 2], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 2, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [3, 0, 0], "block": "minecraft:sticky_piston[facing=east]", "role": "piston" },
    { "pos": [3, 1, 0], "block": "minecraft:sticky_piston[facing=east]", "role": "piston" },
    { "pos": [3, 0, 2], "block": "minecraft:sticky_piston[facing=east]", "role": "piston" },
    { "pos": [3, 1, 2], "block": "minecraft:sticky_piston[facing=east]", "role": "piston" },
    { "pos": [3, 2, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [3, 3, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 3, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 3, 2], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [1, 3, 0], "block": "minecraft:repeater[facing=west,delay=1]", "role": "repeater" },
    { "pos": [1, 3, 2], "block": "minecraft:repeater[facing=west,delay=1]", "role": "repeater" }
  ],
  "propagation_delay_ticks": 4,
  "notes": "4个粘性活塞分上下两组。顶部活塞通过torch tower供电，底部活塞直接供电。中继器同步两组活塞的时序。"
}
```

#### 5.2 Item Sorter（物品分类器 SS1）

```json
{
  "name": "Item Sorter (SS1)",
  "category": "contraption",
  "dimensions": { "width": 4, "height": 3, "depth": 2 },
  "inputs": [
    { "label": "ITEM_IN", "pos": [0, 1, 0], "direction": "west" }
  ],
  "outputs": [
    { "label": "ITEM_OUT", "pos": [3, 0, 0], "direction": "down" }
  ],
  "truth_table": [],
  "blocks": [
    { "pos": [0, 1, 0], "block": "minecraft:hopper[facing=east]", "role": "container" },
    { "pos": [1, 0, 0], "block": "minecraft:hopper[facing=down]", "role": "container" },
    { "pos": [1, 0, 1], "block": "minecraft:redstone_comparator[facing=south,mode=compare]", "role": "comparator" },
    { "pos": [2, 0, 1], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [2, 1, 1], "block": "minecraft:stone", "role": "mount" },
    { "pos": [2, 2, 1], "block": "minecraft:redstone_torch[lit=true]", "role": "inverter" },
    { "pos": [2, 1, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [1, 1, 0], "block": "minecraft:redstone_wire", "role": "wire" },
    { "pos": [3, 0, 0], "block": "minecraft:hopper[facing=down]", "role": "container" }
  ],
  "propagation_delay_ticks": 2,
  "notes": "过滤漏斗放1目标物品+4填充物。比较器读数超阈值→火把灭→下层漏斗解锁→物品掉落。每个通道独立，可横向堆叠。"
}
```

---

## 电路组合规则

### 信号连接约定

1. **方向标准**：输出从 +X（东），输入从 -X（西）。中继器放在两级之间隔离。
2. **信号隔离**：级间必须放中继器（`delay=1`），防止反向馈电。
3. **时序匹配**：多路径到达同一点时，每条路径的延迟必须相等（加中继器补偿）。
4. **信号强度**：每15格必须加中继器刷新。比较器用于保持信号强度值。

### 组合方式（compose）

```javascript
// 从 NOT + AND 构建 NAND
function nandGate(bx, by, bz) {
    andGate(bx, by, bz);            // 先建 AND
    setBlock(bx + 4, by, bz + 1, 'minecraft:repeater[facing=east,delay=1]'); // 隔离中继器
    notGate(bx + 5, by, bz + 1);    // 后接 NOT
}
```

### 层次化构建

```
逻辑门 → 半加器/全加器 → N位加法器 → ALU
逻辑门 → RS锁存器 → 寄存器/计数器
```

---

## 仿真与验证

建造前**必须先仿真**。使用 `simulateRedstoneCircuit` MCP 工具。

### 仿真流程

```
1. 生成电路 JSON（从本 skill 模板）
2. 调用 simulateRedstoneCircuit(circuit=<JSON>, autoTest=true)
3. 工具内部：
   → Python 子进程 → Nucleation SchematicBuilder
   → CircuitBuilder + TypedCircuitExecutor
   → 遍历 truth_table 的所有输入组合
   → 每组合运行 FixedTicks(40)
   → 采集实际输出 → 与预期对比
4. 返回: { passed, results[], timing, errors[], warnings[] }
```

### 仿真结果解读

- `passed: true` → 所有测试向量通过，可以建造
- `passed: false` → 检查 `errors[]` 和 `results[]` 找到不匹配的组合
- `warnings[]` → 信号强度不足、时序临界等问题

### 时序电路的特殊处理

时序电路（RS锁存器、T触发器）的仿真需要多步执行：
1. 先设初始状态（S=0,R=0，仿真20tick稳定）
2. 施加输入变化（S=1）
3. 运行 FixedTicks
4. 检查输出是否锁存

---

## 完整工作流

```
用户需求："在(100,64,200)做一个4位加法器"
  ↓
1. 识别：算术电路 → 行波进位加法器(4bit)
2. 查找模板：全加器 + ripple-carry 参数化模板
3. 生成电路 JSON（含 truth_table）
4. simulateRedstoneCircuit(circuit=<JSON>, autoTest=true)
  → passed: true, delay: 24rt
5. buildRedstoneCircuit(circuit="RIPPLE_CARRY_ADDER", x=100, y=64, z=200, bits=4, facing="east")
  → 生成 /setblock 命令 → Bot 逐块放置
  ✅ 完工
```

---

## 已知限制

- `/setblock` 命令受服务器速率限制（每tick约1条）
- 大电路（>100块）建造时间可能需要数分钟
- 活塞推动上限12块，粘液块粘连上限12块
- 红石火把 burnout：1秒内闪烁超过8次会永久熄灭
- 跨区块边界可能因加载顺序导致时序异常
- Nucleation 仿真不涵盖漏斗物品传输的精确时序（需要 MCHPRS 完整仿真）
- 组合电路（Half Adder/Full Adder/Ripple-Carry Adder）的 `blocks` 为 []，需要 compose 动态展开

## 常见错误

| 错误 | 原因 | 修复 |
|------|------|------|
| 信号不到达 | 距离>15格无中继器 | 加中继器 |
| 火把 burnout | 高频闪烁 | 降低时钟频率或增加延迟 |
| 时序竞争 | 多路径延迟不匹配 | 用中继器对齐延迟 |
| 反向馈电 | 输出信号回流到输入 | 级间放中继器(二极管) |
| 活塞不同步 | 顶部/底部时序差 | 用中继器匹配延迟 |
| 方向错误 | facing 参数不对 | 检查 facing 枚举值 |
| block state 语法错误 | 格式不对 | 用 `minecraft:block_id[key=val]` |


## Nucleation 集成参考

当后续使用 Nucleation 直接生成 schematic 文件时，本 skill 的 JSON 编码可直接映射：

```python
from nucleation import Schematic

schem = Schematic.new("and_gate")
for b in circuit["blocks"]:
    x, y, z = b["pos"]
    schem.set_block((x, y, z), b["block"])
schem.save("and_gate.schematic")
```
