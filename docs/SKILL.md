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

### MC-31100 修复：/setblock 红石元件不激活（已解决，2026-07-25）

**原生 bug**：`/setblock` 放置的红石元件（中继器、比较器、红石灯、红石粉等）不会检测已存在的邻居电源，导致放下去不通电。玩家手动放置则正常——因为手动放置会触发 `neighborChanged` + 二极管的 `checkTickOnNeighbor`。

**解决方案**：Forge 1.21.4 mod `redstone-update-mod`（源码 `~/project/redstone-update-mod/`），通过 mixin 注入 `SetBlockCommand.setBlock` 的 `@At("RETURN")`：

```
1. 对红石元件调 level.neighborChanged(pos, neighborBlock, null) × 6 方向 → 灯/灰/火把检测电源
2. level.updateNeighborsAt + sendBlockUpdated → 通知邻居 + 刷新渲染
3. 中继器/比较器（DiodeBlock）额外用 @Invoker 调原生 checkTickOnNeighbor → 让二极管自己判断输入并调度 tick 更新 POWERED
```

| 元件 | 修复后 `/setblock` 行为 | 验证 |
|------|------------------------|------|
| 红石灯 | 检测邻居电源即时点亮 | ✅ |
| 红石粉 | 检测电源 → power=15 | ✅ |
| 中继器/比较器 | 检测输入 → 通电 → 驱动下游 | ✅ |

> **前置条件**：该 mod 必须已装入 `~/Library/Application Support/minecraft/mods/`。无 mod 时 `/setblock` 电路不通，须回退到玩家物理放置（`bot.placeBlock`，1.21.4 有 timeout 问题）。
> **失败排查**：`DiodeBlock.checkTickOnNeighbor` 只在 `willTickThisTick==false` 时调度 tick——**不要**自己抢先 `scheduleTick`,否则会阻止原生更新。必须调原生方法让它自判。

### ⚠️ 验证陷阱（血泪教训，2026-07-25）

**这两个陷阱曾导致连续十几轮误判 mod "失败",实际 mod 早就工作了。**

| 陷阱 | 错误做法 | 正确做法 |
|------|---------|---------|
| **客户端缓存滞后** | 用 `bot.blockAt(pos)._properties` 读状态——这是 **Mineflayer 客户端缓存**,服务端方块已更新但客户端包未到,读出的是旧值 | 用**服务端查询** `/execute if block <pos> <block>[state=val] run say MARKER`,监听 `MARKER` 消息 |
| **中继器朝向反了** | 以为 `facing` 是输出方向 | `facing` 是**输入方向**：`getInputSignal` 读 `pos.relative(facing)`。红石块在西 → 中继器要 `facing=west`(输入朝西对准电源),输出在东 |

### MCHPRS 仿真规则（nucleation 引擎，2026-07-25 实测）

**建造前用 `nucleation.Schematic` + `nucleation.MchprsWorld` 仿真验证逻辑，再导出 litematic 一次性粘贴（绕过 /setblock 速率与区块加载问题）。** MCHPRS 是精确红石仿真，其规则与游戏基本一致但有几处必须遵守：

```python
import nucleation as n
schem = n.Schematic.create("gate")
schem.set_block_from_string(x, y, z, "minecraft:redstone_wire")
# 每个测试向量重建 schematic，用 redstone_block 注入输入
world = n.MchprsWorld.create_with_options(schem, False, False)  # optimize=False
world.tick(8)                          # 稳定
lit = world.is_lit(x, y, z)            # 读灯
pwr = world.get_redstone_power(x,y,z)  # 读灰电平 0-15
schem.save_to_file("gate.litematic")   # 导出
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `INPUT_SOURCE` | 输入用 `redstone_block`（放置=1/air=0），**每向量重建 schematic** | `set_lever_power`/`on_use_block` 对 lever 不驱动红石 |
| `STANDING_TORCH_SAME_Y` | 站立火把（`redstone_torch` 在方块顶）只给**同层 Y+1 水平相邻**灰供电，**不给下层 Y=0** | torch 在 Y+1、后续灰在 Y=0 的立体布局断路 |
| `WALL_TORCH_PLANAR` | 墙上火把（`redstone_wall_torch[facing=east]` 附着西侧块）全平面工作，是可靠反相器 | 立体火把布局在 MCHPRS 难复现 |
| `STRONG_POWER_STRAIGHT` | 灰强充能实体块的前提：该灰是**直线段末端指向该块**；T 形/汇合分支**不**触发强充能 | NOR 汇合后 torch 常亮——必须再加一段单独直线灰指向下级 mount |
| `OPTIMIZE_FALSE` | 用 `create_with_options(schem, False, False)` | `optimize=True` 可能优化掉无源测试电路 |

**MCHPRS 验证过的平面 AND（4/4，全 Y=0）**：
```
A → stone → wall_torch[east]  (NOT A) ┐
                                       ├→ merge灰(3格) → 直线灰(1格) → stone → wall_torch[east] → 输出灰 → lamp
B → stone → wall_torch[east]  (NOT B) ┘
```
关键：merge 灰汇合两路后，**必须再接一段单独直线灰**指向 final mount，否则强充能不生效（`STRONG_POWER_STRAIGHT`）。

> **游戏布局 vs MCHPRS 布局**：SKILL.md §1.3 的立体 AND（火把 Y+1）在**游戏内** 4/4，但在 **MCHPRS** 断路（`STANDING_TORCH_SAME_Y`）。编译器的 GATE_LAYOUTS 面向 MCHPRS 时必须用**全平面墙上火把布局**。

### 区块加载约束（强制）

**Bot 只能读取已加载区块内的方块状态；且 `/setblock` 目标超出加载半径会静默失败。**

```
❌ 在 X=200 处放置方块，Bot 在 X=0 处读取 → 返回 null；/setblock 也静默失败
✅ 电路建造在 Bot 50 格范围内；或 Bot 边建边 /tp 跟随
```

| 规则 | 约束 | 违反后果 |
|------|------|---------|
| `CHUNK_RADIUS` | 电路必须建造在 Bot 当前位置 50 格范围内 | `bot.blockAt()` 返回 `null` |
| `BUILD_NEAR_BOT` | 建造脚本使用 `Math.floor(bot.entity.position.x) + offset` 定位 | 块在未加载区块中不可读 |
| `SETBLOCK_LOAD_RADIUS` | `/setblock` 目标超出 Bot ~13 区块（~210格）静默失败（实测：240格=0/10，200格=100%） | 远端方块未放置，构建残缺 |
| `CMD_RATE_LIMIT` | `bot.chat` 发命令 > ~150ms/条会被服务端丢弃（实测 200ms=100%，80ms=14%）；`cmd()` 若 async 需真正 `await` 串行 | 突发命令批量丢失，构建 ~50% 残缺 |
| `NO_COORD_OVERLAP` | 多门布局坐标不可重叠（全加器 5 门挤在 10×6 有 10 处碰撞） | 后写覆盖先写，每单元丢 ~6 块 |

### 已验证门模板

以下模板经过游戏内 4/4 全组合测试验证，可直接使用：

| 门 | 验证结果 | 关键特征 |
|----|---------|---------|
| **NOT** | 2/2 ✅ | 1 地面火把 + 1 石块 + 2 灰 |
| **AND** | 4/4 ✅ | 3 地面火把 + 1 墙上火把输出，灰在安装块顶上 |
| **NAND** | 4/4 ✅ | AND + 墙上火把 NOT（门链验证通过） |

### MCHPRS 平面门模板（块级仿真验证）

以下为**全平面墙上火把布局**，经 MCHPRS 块级仿真验证真值表（非游戏立体布局）：

| 门 | MCHPRS | 布局要点 |
|----|--------|---------|
| **AND** | 4/4 ✅ | NOT A / NOT B（墙上火把）→ merge灰 → 直线灰 → final NOT → 输出（见上方图） |

### 未验证门模板

以下逻辑已由行为仿真验证，块级平面布局待 MCHPRS 验证：

| 门 | 逻辑仿真 | MCHPRS 块级 | 下一步 |
|----|---------|------------|--------|
| **XOR** | ✅ | ⏳ | 用平面墙上火把 + `STRONG_POWER_STRAIGHT` 规则布线 |
| **Full Adder** | ✅ | ⏳ | 2×XOR + 2×AND + OR，门间留足间距（`NO_COORD_OVERLAP`） |
| **Ripple-Carry Adder** | ✅ | ⏳ | 全加器链，进位灰同层直连 |

> **核心结论**：可靠路径是 **nucleation.Schematic 建块 → MCHPRS 仿真真值表 → 导出 litematic 游戏内一次性粘贴**。手工逐块 /setblock 受命令速率（`CMD_RATE_LIMIT`）、区块加载（`SETBLOCK_LOAD_RADIUS`）、坐标重叠（`NO_COORD_OVERLAP`）三重限制，不适合大规模电路。门布局必须遵守 MCHPRS 仿真规则（站立火把同层、强充能直线段）。

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

**四步流程：设计 → 写设计代码 → 模拟 → 实践**

```
用户需求："做一个 4-bit CPU"
  ↓
【第一步：设计】
  ISA 定义（字长/指令/寄存器）
  → 数据通路设计（寄存器→ALU→总线→输出）
  → 控制逻辑（时序/状态机/时钟频率）
  → 物理布局（位片/总线位置/Y层分工）
  ↓
【第二步：写设计代码】
  生成结构化 JSON（逐块坐标 + 角色标注 + 真值表）
  → blocks 数组：每块的 pos + block_id + state + role
  → inputs/outputs 端口定义
  → truth_table 验证向量
  ↓
【第三步：模拟】
  调 nucleation 引擎仿真（Nucleation SchematicBuilder + CircuitBuilder）
  → 遍历 truth_table 所有输入组合
  → 每组合运行 FixedTicks(40)
  → 采集输出 → 与预期对比
  → PASS: 进入第四步
  → FAIL: 回第一步修正设计
  ↓
【第四步：实践】
  buildRedstoneCircuit → 生成 /setblock 命令序列
  → Bot 在游戏中逐块放置（CMD_DELAY=200ms + Y层排序）
  → 服务端查询验证（/execute if block ... run say）
  ✅ 完工
```

---

## 红石计算机架构设计方法

> 2026-07-25 实战验证：基于 HashDG Fibonacci 计算机（984 块，4-bit）反向工程 + 游戏内建造测试通过（5/5 灯亮）。

### 设计方法论：从 ISA 到 Schematic

红石计算机的设计与真实 CPU 设计流程同构——本质上是从指令集架构（ISA）到寄存器传输级（RTL）再到物理布局的逐层细化：

```
ISA 定义 → 数据通路设计 → 控制逻辑 → 时序分析 → 物理布局
```

### 核心组件目录

红石计算机由以下基本组件构成，每个都有 Minecraft 中的标准实现方式：

#### 1. 寄存器（Register）— 存储单元

**原理**：锁存中继器（`locked=true`）在锁定后保持输出信号不变，构成 1-bit 存储。

```
实现：repeater[facing=east,locked=true]
写入：解锁 → 信号输入 → 锁定（锁存）
读取：中继器输出端永远反映存储值
```

每个 4-bit 寄存器需要 4 个中继器（每个 bit 一个），垂直排列或水平排列。解锁/锁定信号通过独立的控制线传递。

**关键约束**：
- 锁存中继器的 `locked` 输入端（侧面）接到控制火把
- 写入前必须先解锁，写入完成后锁定
- 解锁→写入→锁定的最小时间窗口 = 2rt（2 个红石刻）

#### 2. ALU（算术逻辑单元）— 计算核心

**原理**：红石比较器在减法模式下实现信号强度运算。

```
比较器 subtract 模式：output = max(0, rear - max(sideA, sideB))

关键公式：
- 信号传送：直接线连，信号强度 = 源强度 - 距离衰减
- 常数生成：红石块 = 15，红石火把 = 15（墙面火把 lit=true）
- 减法：比较器 rear=15, side=value → output=15-value
- 加法（通过两次减法）：A + B = 15 - ((15 - A) - B)
```

**Fibonacci 计算机中的实现**：
- 两个比较器串行（第一级：rear=15, side=RegA → 15-A；第二级：rear=第一级输出, side=RegB → (15-A)-B）
- 再经过一个比较器取反 → A+B

#### 3. 总线（Bus）— 数据传输

**原理**：红石粉沿一个方向排列，多个组件连接到同一条线。

```
物理总线：Z=常量的一条红石粉线（如 Z=8 从 X=1 到 X=15）
连接方式：组件输出通过中继器（二极管隔离）接入总线
多个驱动源：分时复用（控制逻辑保证同一时刻只有一个写入）
```

**规则**：
- 总线上的每个写入端必须有中继器隔离（防止反向馈电）
- 总线读取端可以直接连线
- 同一时刻只能有一个设备驱动总线

#### 4. 控制单元（Control Unit）— 时序中枢

**原理**：红石火把 + 中继器延迟链生成控制信号序列。

```
时钟源：
- note_block + observer：手动单步（每次右键一个脉冲）
- 中继器环形振荡器：自动时钟（2×delay rt 周期）
- 活塞 + observer：自动时钟（扩展+收回各触发一次）

控制信号生成：
- 火把 NOT 门 → 反相
- 中继器延迟链 → 多相时钟
- 火把 burnout 保护：中继器 delay≥2 抑制高频
```

**Fibonacci 计算机的时钟方案**：
- 3 个 note_block + observer 提供三条独立的控制脉冲线
- 一条控制"手动步进"，一条控制"自动时钟开关"，一条控制"复位"
- reset 通过活塞推动 purpur_block 来切断时钟信号

#### 5. 输出显示（Output Display）

**原理**：红石灯直接接到输出总线的每一位。

```
每位输出 = 1 个 redstone_lamp
N-bit 输出 = N 个 lamp 垂直或水平排列
二进制显示：从上到下 = MSB → LSB
```

### Fibonacci 计算机架构案例

这是实战验证过的唯一完整计算机架构，984 块，16×14×20 尺寸。

#### 物理布局（俯视图）

```
Z=19  ┌──────────────────────────────────┐
Z=18  │  数据寄存器 B (X=6)              │
Z=17  │  RegB 输出灯                     │
Z=16  │  锁存使能控制线                  │
Z=15  │  信号交叉点                      │
Z=14  │  ALU 第二级（比较器链）          │
Z=13  │  ALU 第一级                       │
Z=12  │  常数 15 参考（火把）            │
Z=11  │  控制脉冲生成                     │
Z=10  │  purpur_block 时钟隔离           │
Z=9   │  数据寄存器 A (X=4)              │
Z=8   │  ===== 主数据总线 =====          │
Z=7   │  寄存器写入选择器                 │
Z=6   │  信号路由交叉                     │
Z=5   │  lamp 输出位 3                    │
Z=4   │  寄存器读取使能                   │
Z=3   │  lamp 输出位 0                    │
Z=2   │  控制面板（note_block×3+木牌）   │
Z=1   │  活塞 + observer 时钟发生器       │
Z=0   │  结构基底（混凝土）              │
      └──────────────────────────────────┘
      X=0                           X=15
```

#### 位片结构（侧视图，以 bit 0 为例）

```
Y=11  [lamp] ← 输出显示
Y=10   ─┬─ 垂直信号线（进位传递）
Y=9    ├── 位 3 数据寄存器 A (repeater locked)
Y=8    ├── 主数据总线（水平红石粉 Z=8）
Y=7    ├── 位 2
Y=6    ├── 控制脉冲（火把）
Y=5    ├── 位 1
Y=4    │   寄存器 B (comparator + repeater)
Y=3    ├── 位 0 数据寄存器
Y=2    │   控制逻辑层（comparator + torch）
Y=1    ├── 时钟输入（observer → 脉冲）
Y=0    └── 结构基底
```

每个 bit 垂直占据 2 个 Y 层（奇数层=数据，偶数层=控制），5 个 bit 共占用 Y=3 到 Y=11。

#### Fibonacci 算法硬件实现

```
算法伪代码：
  R1 = 0, R2 = 1          // 初始值（硬连线）
  LOOP:
    display(R2)           // 输出当前值
    tmp = R1 + R2         // ALU 计算
    R1 = R2               // 移位
    R2 = tmp              // 存储新值

硬件实现：
  1. Comparator chain at X=6-14 computes R1+R2 via signal strength subtraction
  2. Result feeds into register B at X=6 via repeater latch
  3. Old R2 value moves to register A at X=4 (via bus at Z=8)
  4. R2 lamp at X=5 displays current Fibonacci number
  5. Clock pulse advances to next iteration
```

### 设计方法：从零开始设计一个红石计算机

参考 Hennessy & Patterson 的"量化研究方法"改编为红石领域：

#### Phase 1：指令集架构 (ISA) 定义

决定计算机做什么、怎么做：

```
1. 字长：4-bit 还是 8-bit？（影响所有组件规模）
2. 指令数：需要哪些操作？（ADD, SUB, LOAD, STORE, JUMP...）
3. 寄存器数：几个通用寄存器？
4. 寻址模式：立即数、直接寻址、寄存器间接？
5. I/O：输入方式（拉杆/按钮）和输出方式（灯/7段管）
```

#### Phase 2：数据通路设计

画出数据如何流动：

```
1. 寄存器堆 → 画出每个寄存器的宽度和位置
2. ALU → 确定算术操作的比较器链拓扑
3. 总线 → 规划共享数据通路（宽多少格、位置在哪）
4. 多路复用 → 如何选择哪个寄存器驱动总线
5. 画出数据流图：RegA→Bus→ALU→RegB
```

#### Phase 3：控制逻辑设计

时序和状态机：

```
1. 指令周期 = 取指 + 译码 + 执行 + 写回（每步 2-4rt）
2. 控制信号表：对每条指令列出所有控制信号
3. 状态机：用火把+中继器链实现状态序列
4. 时钟频率 = 最长控制路径延迟（**测量，不要估计**）
```

#### Phase 4：物理布局

块的物理放置：

```
1. 位片布局：每个 bit 一个垂直切片（便于布线）
2. 数据总线居中：所有组件通过中继器接入
3. Y 层分工：奇数=数据（总线、寄存器），偶数=控制（火把、脉冲）
4. 非导电隔离：混凝土/玻璃保证信号不串扰
5. 标牌标注：用电线连接处的 oak_wall_sign 标记信号名
```

#### Phase 5：构建与验证

```
1. 最小可行产品：先建 1-bit 通路验证 ALU+寄存器工作
2. 扩展到 N-bit：复制位片 N 次
3. 单步测试：用 note_block observer 手动触发每个指令
4. 自动化测试：用 bot /execute if block 查询每个 lamp
```

### 关键设计约束

| 约束 | 值 | 设计影响 |
|------|-----|---------|
| 信号最大距离 | 15 格（无中继器刷新） | 总线超过 15 格必须加中继器 |
| 中继器延迟 | 1-4 rt（可调） | 每条控制路径的延迟 = Σ 沿途中继器的 delay |
| 火把 burnout | >8 次闪烁/秒 永久熄灭 | 时钟频率必须 < 4Hz（周期 >5rt） |
| 比较器延迟 | 1 rt（固定） | 减法运算需要 2rt（2 级串行比较器）|
| 锁存中继器 | 锁定后不更新 | 写入前必须解锁至少 1rt |
| 活塞延迟 | 3-4 gt（1.5-2 rt） | 不适合高频时钟，适合复位/使能 |
| 充能规则 | 强充能传递 15 信号 | 红石块直接邻接 = 强充能 = 信号 15 |

### 已验证可用的计算机模板

| 计算机 | 位宽 | 块数 | 指令 | 时钟 | 验证 | 特点 |
|--------|------|------|------|------|------|------|
| **Fibonacci 计算机** (HashDG) | 4-bit | 984 | ADD only (硬连线) | note_block 手动 | ✅ 5/5 灯亮 | 2 寄存器 + 累加器 |
| **RCA-8** (合成) | 8-bit | 143 | — | — | ✅ 模拟 8/8 | 纯组合逻辑加法器 |
| **Acc-8 CPU** (合成) | 8-bit | 605 | LOAD/ADD/CLEAR | 手动步进 | ✅ 模拟 8/8 | 累加器架构，Python 仿真通过 |

---

## 红石显示系统设计

> 2026-07-25：为"视频显示机器"目标设计。从 Fibonacci 计算机和 DIKC-4 架构中提取可复用模式。

### 显示系统架构

```
┌──────────┐    ┌──────────┐    ┌────────────────┐
│  CLOCK   │───▶│ ADDRESS  │───▶│  FRAME ROM     │
│ Generator│    │ COUNTER  │    │ (analog sig.)  │
└──────────┘    └────┬─────┘    └───────┬────────┘
                     │                  │
                     ▼                  ▼
              ┌──────────────────────────────────┐
              │     DISPLAY CONTROLLER           │
              │  ┌────────────┐ ┌────────────┐   │
              │  │ROW DECODER │ │COL DECODER │   │
              │  │(4→16 comp.)│ │(4→16 comp.)│   │
              │  └────────────┘ └────────────┘   │
              │         │            │            │
              │         ▼            ▼            │
              │    ┌─────────────────────┐        │
              │    │   LAMP MATRIX       │        │
              │    │     16×16 = 256     │        │
              │    └─────────────────────┘        │
              └──────────────────────────────────┘
```

### 组件设计

#### 1. 地址计数器 (Address Counter)

**原理**：T 触发器链，每个触发器输出频率为输入的 1/2。

```
8 个 T 触发器串联 → 256 状态（0-255）
每个触发器 = 1× Dropper-Hopper TFF (3×3×3, ~12 blocks)
总计：8 × 12 = ~96 blocks

或使用 Observer+Repeater 环形计数器（更紧凑）
```

**设计约束**：
- 时钟频率必须 < TFF 最大频率（~2.5 Hz，因 Dropper 延迟）
- 计数器输出 = 8-bit 并行（每位一根红石线）

#### 2. 帧 ROM (Frame ROM)

**原理**：类似 DIKC-4 的信号强度编码存储器。

```
64 个"barrel"（每个 8 块）
每 barrel 存储 4-bit 信号强度（0-15）
地址输入 → 多路选择 → 输出对应 barrel 的信号强度

DIKC-4 的指令 barrel 模式：
  bottom barrel = opcode signal strength
  top barrel = operand signal strength
```

**Frame ROM 适配**：
- 2D 排列：8×8 barrel grid = 64 个存储单元
- 每个输出 4-bit 信号强度
- 地址 = 6-bit（高位=row，低位=col）
- 读周期 = ~3rt（比较器选通 + 中继器锁存）

#### 3. 行列解码器 (Row/Column Decoder)

**原理**：比较器链实现 4-to-16 译码。

```
4-bit 输入 → 16 条输出线，每次只 1 条激活
实现：16 个比较器，每个匹配不同的 4-bit 值
每个比较器：rear=输入信号, side=基准值 → 匹配时输出=0

简化方案（推荐）：
  使用 target block（标靶）接收 address bus 信号
  target 的 power 值直接驱动对应 lamp 列
```

#### 4. 灯矩阵 (Lamp Matrix)

**原理**：N×M 红石灯网格，行列交叉选通。

```
16×16 = 256 lamps，排列方式：
  行选择：水平红石线（16 条）
  列选择：垂直红石线（16 条）
  交叉点：中继器 + lamp
  
每个 lamp = 1 redstone_lamp + 1 repeater（隔离）
总计 = 256 lamps + 256 repeaters + 32 wires ≈ 800 blocks
```

### 帧格式与 ROM 布局

```
16×16 帧 = 256 bits = 64 nibbles (4-bit each)
ROM 组织：8 rows × 8 columns of barrels

每个 nibble 映射到 frame 的一个 2×2 像素块（简并）
或使用 8×8 每个 pixel 独立（单色）

多帧动画：ROM 分成多个 bank，bank 地址 = 帧号高位
例如：4 帧动画 = 256 nibbles = 1024 bits = 128 bytes ROM
```

### 建造估算

| 模块 | 块数 |
|------|------|
| 灯矩阵 (16×16) | ~800 |
| 行/列译码器 | ~200 |
| 帧 ROM (64 nibbles) | ~500 |
| 地址计数器 (8-bit) | ~100 |
| 时钟 + 控制 | ~50 |
| 结构/隔离 | ~350 |
| **总计** | **~2000 blocks** |

帧刷新率：64 步 × 0.5s/步 ≈ **32 秒/帧**（手动时钟）
自动时钟（2 Hz）≈ **32 秒/帧** → **0.03 fps**

### 已知限制

- 红石灯有 2rt 点亮延迟（影响动画刷新）
- 比较器译码器需要精确的信号强度校准
- 大型灯矩阵的电源分配需要精心设计
- 超 15 格需要中继器刷新（限制矩阵尺寸）
- **MCHPRS 不仿真红石火把**（模拟器局限，不影响实际建造）

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
| 方向错误 | facing 参数不对（facing 是**输入**方向,非输出） | 电源在西 → 中继器 `facing=west` |
| block state 语法错误 | 格式不对 | 用 `minecraft:block_id[key=val]` |
| `/setblock` 红石元件不通电 | MC-31100，新方块不检测邻居电源 | 装 `redstone-update-mod`（见 /setblock 命令约束段） |
| 误判方块状态（假"未通电"） | 读 `bot.blockAt` 客户端缓存滞后 | 用服务端 `/execute if block ... run say` 查询 |


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

## 大规模电路综合管道（redstone3d 包）

超出手写规模（>几门）时，用 `mcp-server/scripts/redstone3d/` 的自动综合管道：
**Verilog → yosys 综合 → 标准单元库 → 三维布局 → 迷宫布线 → 分层验证 → litematic**。

### 模块与流程

```
yosys_frontend.py  Verilog → yosys+abc(-g AND,OR,NAND,NOR) → 门级 netlist
                   全加器 19门手写NAND展开 → 7门；8-bit ALU → 160门
cell_library.py    MCHPRS验证过的标准单元(统一引脚:输入西/输出东,全y=0)
                   NOT/BUF/OR/AND/NAND/NOR 各4/4。输入引脚用 repeater(侧向进入安全)
placer.py          拓扑分层布局(X=逻辑深度,Z=同层并排),体素占用防重叠
maze_router.py     Lee迷宫布线 + rip-up&reroute(协商式拥塞),扇出树形
synth.py           netlist→place→route→Schematic + redstone_block输入注入
mchprs_sim.py      逐向量重建world仿真(redstone_block注入,4ms/向量)
regress.py         分层验证:物理(每cell MCHPRS 4/4) + 逻辑(netlist行为仿真)
```

### 关键规则（血泪实测）

| 规则 | 内容 |
|------|------|
| `YOSYS_ABC_GATES` | `abc -g AND,OR,NAND,NOR` 映射到可建门集；yosys 大幅优化门数/扇出 |
| `MCHPRS_INPUT_INJECT` | lever/set_lever_power/set_signal_strength **不驱动**网络；只能用 `redstone_block`放置/移除注入，每向量重建 world |
| `OPTIMIZE_TRUE` | `create_with_options(schem, True, False)` 绕过 `optimize=False` 的 255-default-input 上限 |
| `FANOUT_FROM_WIRE` | 扇出分叉必须从 **wire** 而非 pin（repeater/门不横向导通） |
| `DIAGONAL_RAMP_SHORT` | 红石线斜上/斜下连接：不同 net 的线在对角位置**短路**。布线 keep-out 必须查对角，否则连通图污染 |
| `NO_FLOATING_DUST` | 悬空红石线（下方无实心块）让 redpiler **卡死**；每 wire 下必有支撑，且垂直移动重惩罚强制平面布线 |
| `DUST_DENSITY_ON2` | 密集红石粉图边数 O(N²)（N×N 实心 dust ≈ N² 边，是 dust 全互连的语义正确行为，**非 bug**）。布线越密集 create 越慢。对策：布线减 dust 密度（短路径/留间距）+ 大电路用分层验证免整体仿真 |

### 分层验证（突破规模上限的核心）

大电路整体 MCHPRS 编译因密集 dust 的 O(N²) 图而变慢。改为两段独立证明：
- **物理层**：每个 cell 类型在 MCHPRS 验证真值表一次（小电路，秒过）
- **逻辑层**：netlist 用纯 Python 行为仿真（组合逻辑精确，无规模上限）

物理正确 ∧ 逻辑正确 ⟹ 整体正确。已验证：全加器 8/8、8-bit ALU 80/80（AND/OR/ADD/XOR/SUB 各16组）。可扩展到整个 RISC-V。

### 已达成

| 电路 | 门数 | 验证 |
|------|------|------|
| 全加器 | 7（yosys优化） | 分层 8/8 + litematic导出 933B |
| 8-bit ALU | 160 | 分层 80/80 |

> **规模瓶颈**：整体布线（rip-up）在 >100 门时慢（分钟级），密集 dust 让整体 MCHPRS 仿真的图 O(N²) 增大。分层验证绕过整体仿真；大电路整体布线优化（分块布线/减 dust 密度/更快算法）为后续项。
