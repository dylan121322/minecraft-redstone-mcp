# 红石布线器完整技术日志 (RISC-V → Minecraft)

> 本文件承载 RISC-V→红石布线器的全部技术细节、验证结果、失败教训。
> 从 memory 迁出集中管理。项目: fundamentalLabs-minecraft-mcp。
> 服务器: frp-tag.com:40269 (creative, vanilla 1.21.4, 无 MC-31100 mod)。

---

## 一、核心问题:布线器的假合法性

`maze_router.py` 的 `route_negotiated()` (PathFinder) 声称 `shared==0` 就"LEGAL",
即没有体素被两个网占用。但真实红石里,两个不同网的 dust 只要满足以下任一就短路:
- 同 Y 正交相邻(水平短路)
- 同 X,Z 相差 1 Y(垂直短路)
- 对角 ramp (dx, dy±1, dz) —— dust 爬一步就连上

`route_negotiated`/`_cost_bfs` 从不做这些检查(只有 `_bfs` 平面模式调 `_foreign_adjacent`,
但那模式在密集模块留下未布通的网)。

**实测 alu1 (24门, col_gap=16):** route_negotiated failed=0 但 181 垂直 + 696 对角 +
415 水平短路 + **833 悬空线**(抬升 dust 下方无支撑)。route() 5-pass: 0 短路但 7 网未布通 + 763 悬空。

**死路确认:** 强制平面 (y_max=0) 永不合法——网必须交叉,同平面两 dust 交叉必短
(alu1 即使 652 宽间距仍卡在 31-48 shared)。

---

## 二、验证过的红石物理原语 (MCHPRS + 游戏内)

### /setblock 基础规则
- **无方块更新**: /setblock 放置的红石元件不触发邻居更新。dust 驱动输入可靠,
  redstone_block 直接贴 dust 注入不可靠(反复踩坑)。
- **命令速率**: 200ms/条安全;距离 ≤210 格(超出静默失败,需 teleport bot 靠近)。

### 6 门标准 cell (游戏内各 4/4)
NOT/BUF 2/2, AND/OR/NAND/NOR 4/4。cell 输入引脚是 `repeater[facing=west]`,从西侧 (px-1) 读信号。
**cell 本身无缺陷**(两个子 agent 都甩锅 cell,均被我用孤立 NOT 测试证伪:
drive=0→out=15, drive=1→out=0)。

### Repeater facing 约定 (nucleation/MCHPRS 实测)
信号流向 → 所需 facing (facing = 流向的反面):
- +x (东) → facing=**west**
- -x (西) → facing=**east**
- +z (北) → facing=**north**
- -z (南) → facing=**south**
搞反会让 repeater 不导通,信号"凭空消失"(像衰减,实则断路)。

### Bridge gadget (Agent A, 游戏内 4/4, test_agentA_ingame.cjs)
+x flow, start (sx,sz) goal (gx,sz), gx-sx>=7:
```
rep[facing=west]@(sx+1,y0)
block@(sx+2,y0) + dust@(sx+2,y1)
block@(sx+3,y1) + dust@(sx+3,y2)
run sx+4..gx-2: support block@y1 + dust@y2
descend: block@(gx-1,y0) + dust@(gx-1,y1); dust@(gx,y0)
```
隔离间隙 = y1 实心块在被跨越 y0 线上方 1 格。

### 隔离规则 (Agent B, MCHPRS 实测, AGENT_B_isolation.py)
- **PARALLEL_Y2_MIN_SEP=2**: 两条平行 y2 bridge dust 中心距 ≥2 (sep=1 耦合)
- **CROSSING_IS_ISOLATED=True**: y2 bridge 跨越任意 y0 线永远隔离 (2 格垂直间隙,有无 y1 块都行)
- **SUPPORT_COLUMN_KEEPOUT=0**: y1 石支撑柱不导电,y0 线可贴着走
- **RAMP_KEEPOUT=2**: 爬升/下降 ramp (裸露 y0+y1 dust) 需 Chebyshev ≥2 远离外部 y0 线

### 火把塔垂直传输 (test_vertical.py V2, test_tower_iso.py) ★关键元件
占地 **1×1** 竖柱,替代占 4 格的横向 staircase:
```
底部方块 (经 repeater[facing=west] 供电) 
→ 循环 { 顶部 standing redstone_torch; 火把顶部再放方块 }
```
每个火把反相一次,偶数火把 = 非反相传输。
- 上传验证: drive=0→torch-lit [1,0,1], drive=1→[0,1,0] (每层 NOT)
- **相邻塔 sep=1 即绝缘**(石柱阻断耦合),可紧密排布
- 端到端 gate→塔→gate 传输正确 (test_tower_route.py)
- 注意: 火把塔天然**向上**传;向下传棘手(D1 直下失败),下降仍用 +x staircase 或 descend-into-pin

### 双层 via 爬升 y0→y2→y4 (test_hv_layers.py Q1, 实测电力到顶)
```
rep → block@y0+dust@y1 → block@y1+dust@y2 → block@y2+dust@y3 → block@y3+dust@y4
```

### H×V 分层交叉隔离 (test_hv_layers.py Q2, PASS 4/4) ★架构基石
net A 的 H-dust@y2 与 net B 的 V-dust@y4 在同 (x,z) 交叉,中间 y3 实心块隔开 = **完全隔离**。
不同网的 H 段和 V 段永不短路(不同 y 层 + 实心隔离)。

### 下降原语
- **descend-into-pin** (test_descent_pin.py, MCHPRS OK): 西向 repeater 引脚 @(px,0,pz) 由
  y2 dust@(px-3,pz) → block@y0+dust@y1@(px-2,pz) → y0 dust@(px-1,pz) 喂入。NOT 正确反相。
- **+x staircase 下降** (无 repeater, see-below 规则): power 15→10 落到 y0。
- **descend y4→y0 +x staircase**: 每 +x 步降一层,y4→y3→y2→y1→y0。

---

## 三、尝试过的四种布线器 (全部有缺陷)

| 方案 | 短路 | wire 膨胀 | 结论 |
|------|------|-----------|------|
| 1. 自由 3D 迷宫 (route_buildable 旧) | 671 悬空 | - | 不收敛 |
| 2. 贪婪 2 层 bridge (route_buildable._bridge) | 61 | 1.0x | bridge 顺序不协调 |
| 3. 结构化预留轨道 (route_tracks.py TrackRouter) | 749 | - | 垂直分支横穿其他网行 |
| 4. 全局网格 2 层曼哈顿 (route_channel.py) | **0** | 12.2x | 0短路但严重膨胀 |

### 短路收敛历程 (route_channel)
1292 → 749 → 281 → 197 → 11 → 6 → **0**

关键转折:
- 197→11: 火把塔替代横向 staircase(消除中间-dust 短路)
- 6→0: row_gap 10→14(主输入 z 通道不再与最左列 sink 相邻)

### route_channel 达成 0 短路的配置
`place(col_gap=16, row_gap=14)` → alu1: shorts=0, floats=0, failed=0
(我自己的 legality 检测核验)。dims 300×53, ~24915 wires。

---

## 四、两版本的结构性 tradeoff (核心认知)

- **route_channel (全局网格)**: 0 短路,但 12.2x wire 膨胀。每个网绕行到远处 trunk 行/列
  (n25 源汇在 x=9-26,却被拉到 x=336,z=150 再绕回 = 33x)。row_gap/col_gap 间距有效(真全局轨道)。
- **route_buildable (最短路)**: 1.0x wire (17/29 网 flat),但 60-61 短路 + 2 未布通。
  短路是**算法缺陷非拥挤**——加宽 row_gap 10→24 短路纹丝不动(还是 60),只增 wire。

### route_buildable 短路的结构性根因
route() 先做全部 flat 路由(只登记 owner0 @y0),**之后**才逐个布 bridge。
bridge 顺序布,先布的看不见后布的 → 布 bridge 时冲突检测是瞎的 → 同列相邻 z 的 sink 必撞。
实测:中间区 24/26 短路是 bridge 落地,flat-vs-flat 几乎干净(只 2)。
staggered-descent 补丁无效(y0_conflict 检查看不到未来的网)。

**结论:任何单遍方案都给不了"既精简又 0 短路"。**

---

## 五、正确的下一步:迭代 RIP-UP & REROUTE

像真实 VLSI 详细布线器:
1. 全布所有网(最短路)
2. 检测相邻冲突(真实 adjacency + 悬空 + 火把塔合法性,不是假的体素占用)
3. 撕掉冲突网,按代价场(惩罚争用格)重布
4. 迭代到 0 短路

这样只在真正需要处绕行,既接近最小 wire 又 0 短路。
基础: route_buildable 精简骨架 + 真实合法性检测。
`maze_router.py` 有 route_negotiated 骨架但用了假合法性(体素占用非相邻)。

**不要再打单遍布线器的补丁(已证不收敛)。**

### rip-up 实现进展 (route_ripup.py, RipupRouter)
已实现:cost-aware A* (代价 = 长度 + SHORT_PEN×shell拥塞 + history) + negotiated 迭代
(检测相邻短路→争用格 history 累加→全部重布)+ present-cost(用上轮完整 occ 打破关联翻转震荡)。
精简度极好:**1.3x wire**(2077-2370,接近曼哈顿最小),0 未布通。

**但短路不收敛**:在 134-214 间震荡,降不到 0。根因不是算法震荡,是 **y0 单平面容量不足**——
alu1 29 个网挤在 300×41,冲突涉及 19/29 个网、26 对,平面根本容不下这么多互不相邻的树。
这与早先"planar 死路"同源:网必须交叉,单平面两 dust 交叉必短。

### rip-up 的正确形态:3D 多层 negotiated
rip-up 要收敛到 0,A* 必须**自由使用多层**(y0 + 火把塔爬到 y2 走一段再下来),
代价函数里 y2 层也计拥塞,把负载从 y0 分散到多个平面。这统一了"最短路"和"必要时换层"。
需要把 `_astar` 从 2D(y0 平面)扩展到 3D(节点含 y,可爬火把塔换层,换层有代价)。
- 状态: (x, z, layer),layer ∈ {0, 2}(或更多)
- 转移: 同层 4 邻域移动(代价 1+拥塞);换层 = 火把塔 via(代价高,占 climb 几何)
- 短路检测: 每层独立跑 8 邻域 + 层间垂直/对角
- history 惩罚跨层争用格
这是 rip-up 的自然 3D 推广,是"精简 + 0 短路"的完整解。下一步实现方向。

---

## 八、GPU 枚举方案 (Win 5080 + 9950X3D) —— 环境已核实

**推翻旧记录**:memory 曾说 Win Python 3.14 无 torch/cupy wheel。实测发现 Win 有
**`E:\py312\python.exe` = Python 3.12.9 + torch 2.12.0.dev+cu128, CUDA 可用, 识别 RTX 5080**。
GPU 枚举方案在 Win 端完全可行。

### Win 端环境 (2026-07-27 实测)
- SSH: `sshpass -p '...' ssh -p 59325 administrator@yd.frp-one.com` (见 windows-environment)
- GPU: RTX 5080, 16GB, 驱动 595.79
- Python: `py`=3.14.3 (无torch) | **`E:\py312\python.exe`=3.12.9 + torch cu128 (用这个)**
- numpy 2.4.6; 无 cupy; **无 nucleation / yosys / 项目代码**
- GPU 性能实测: matmul 4096² ×20 = 0.376s; **Lee 波前松弛 3×300×300 ×200轮 = 0.163s**

### 分工 (Mac 综合验证 + Win 纯 GPU 布线)
- **Mac**: yosys 综合、placer 放置、MCHPRS 仿真验证、nucleation bot 建造
- **Win 5080**: 纯 GPU 布线计算(收占用/代价张量 → 返回路径),SSH/scp 传数据
- 一致于既有 Win compute offload 模式

### 张量规模 (x*z*3层*网, placer col_gap=16 row_gap=10)
- alu1 1.1M / Control 0.79M / Mux 0.72M / ALU_Control 2.5M / Imm_Gen 2.9M / Forwarding 30M
- 5080 16GB 显存充足;波前松弛 0.16s/200轮 → GPU negotiated 布线极快

### GPU 3D negotiated 布线设计
核心算子 = **并行 Lee 波前距离场**(GPU 逐元素 min-relax,已测 0.16s):
- 布线空间 = 3D 张量 (layer ∈{y0,y2} × X × Z);cost 张量 = 1 + SHORT_PEN×拥塞 + history
- 每轮: 对每个网并行做波前扩散求距离场 → 回溯最短路 → 检测冲突张量 → history 累加 → 重算
- 换层 = 火把塔 via(y0↔y2),波前在 layer 维度也松弛(via 代价高)
- GPU 枚举变体: 同时跑 N 组 (SHORT_PEN × HIST_INC × 网序) portfolio,选先到 0 短路的
- 短路检测 = 张量卷积(3×3×2 核查相邻),GPU 一次算完全场
这统一了"3D 多层 + GPU 枚举 + negotiated rip-up",是精简且 0 短路的完整解。

### GPU 实现进展 (route_gpu.py, 2026-07-27, Win 5080 实跑)
**全 Win 环境已搭好**:E:\project\scripts (scp 传的代码) + nucleation 0.8.0 + torch cu128 + oss-cad-suite 下载中。netlists.json (6 模块网表, Mac 综合) 已传 Win。
运行: `E:\py312\python.exe route_gpu.py <模块> <层数>`。同步脚本 /tmp/winrun.sh (Mac→Win scp+run)。

**已实现且跑通**:
- `wavefront_batched`: (N网, L层, X, Z) 张量,一次 GPU kernel 松弛所有网的 Lee 距离场。全异步(去掉每步 torch.equal sync,那是最初的性能杀手)。
- `route()`: negotiated 循环 = 批量波前 → CPU backtrace 各网各 sink → `_short_cells`(GPU 卷积检测真实相邻短路,含层内 8 邻域 + 层间垂直/对角)→ history 累加 → 迭代。
- pin 从 block mask 挖出(cell occupancy 含引脚,曾误当障碍致 sink 不可达 = wires 0 的空路由 bug)。
- 层数可配 (L=2/4/...),GPU 对加层几乎不敏感(多一维张量)。
- 性能: alu1 (29网, 2层 313×54) 40 迭代 108s;4 层 133s。5080 GPU 96% 占用。

**未收敛**: 短路震荡不到 0。L=2 最优 289,L=4 最优 190,wires ~2200-2335(精简度好 1.3x)。
根因 = PathFinder **并行全体同刷震荡**(所有网每轮同时从源重 flood → 关联翻转)。present-cost(看上轮 occ)+ history 累加缓解不足。加层(L=4)改善有限——不是容量,是收敛策略。

**下一步(GPU 枚举收敛)**:两条,你最初点名"偏向 GPU 枚举":
1. **GPU portfolio 枚举**: 并行跑 K 组 (随机网序 × short_pen × hist_inc × 随机种子扰动),各自独立 negotiated,取先到 0 短路者。5080 显存够跑 K=8-16 并行。
2. **顺序 rip-up 而非全体同刷**: 每轮只 rip 冲突最多的少数网重路由,其余冻结(消除关联翻转)。难批量但收敛稳。
框架已就绪,只需换收敛策略。route_gpu.py 的 wavefront_batched/_short_cells/backtrace 可复用。

### GPU portfolio 枚举实现 + 能力边界 (2026-07-27)
实现了 `route_portfolio`: 多组变体 (short_pen × hist_inc × jitter × seed),jitter =
随机 per-cell history 初值扰动,打破对称场的关联翻转震荡。取先到 0 短路者。
实测 alu1:
- L=4 紧凑布局: portfolio 最优 132 (jitter 有效,从单变体 190 降到 132)
- L=6 宽布局 (col24 row20, 401×84): 最优 115
- 结论: 加层/加间距只微降 (132→115),**短路有 ~115-130 收敛地板,到不了 0**。

**根本结论 (纯 negotiated 波前的能力边界)**: 每个 sink 从源独立最短路 flood →
同网多条路径 + 不同网路径在**源区**(西边缘 29 个源挤着)放射状重叠 → 必然短路。
这是 negotiated 波前的结构地板,jitter/portfolio/多层都突破不了。

**已达成 0 短路的唯一方案仍是 route_channel 的预分配轨道** (row_gap=14, 0短路/12x膨胀)。
GPU negotiated 精简 (1.3x) 但有短路地板;预分配轨道 0 短路但膨胀。
真正"精简+0短路"需要: 预分配轨道的**无冲突保证** + negotiated 的**最短路精简**结合。
候选: (a) GPU 上做预分配轨道的并行搜索 (给每网分配 layer+track,GPU 枚举 track 分配组合);
(b) negotiated 后对残留 ~115 短路做确定性 rip-up-to-tower (冲突网抬到专属层)。
GPU 基础设施 (route_gpu.py: wavefront_batched/_short_cells/portfolio) 完备可复用。

### 方案 b: 冲突图着色分层 (2026-07-27, route_layered/route_layer_confined)
思路: negotiated 得基础布线 → 建冲突图 (`_conflict_graph`, GPU) → 容量约束贪心着色
(每层 ≤CAP 网且层内互不冲突) → 每层组批量重路由,限制在该层。
实测 alu1:
- 冲突图 3 着色 (CAP 无限: 17/7/5 网) 或 5 着色 (CAP=6: 各 6 网)
- **稀疏层成功**: layer 3/4 (5-6 网) 层内短路 = 0 ✓ 证明稀疏层能 0 短路
- **拥挤层失败**: layer 0/1/2 仍有层内短路 (27/23/8) — 同层 6 网重路由后新产生相邻
- **跨层短路暴增 (723)**: 所有层的网 via 都下到 layer 0 pin 平面,不同层的 via 底部在 layer 0 相撞

两个未解问题:
1. 层内: 同色网重路由后新相邻 (着色只保证 base 布线无冲突,重路由位置变)。需层内也强 negotiated 或更小 CAP。
2. via/pin: 所有网的引脚在 y0,不同层网的 via 竖直段在 y0 附近混叠。需要 via 也做层内 track 分配,或 pin 平面单独隔离。

**方向验证成功** (稀疏层 0 短路),但 via-to-pin 的跨层无冲突处理未完成。这是分层方案的收尾难点。

### 全局状态小结 (三条路的天花板)
- route_channel 预分配轨道: **0 短路达成**, 12x 膨胀 (row_gap=14) — 目前唯一 0 短路
- route_gpu negotiated: 1.3x 精简, 短路地板 ~92-147
- route_gpu 分层着色: 稀疏层 0 短路可行,但 via/pin 跨层混叠未解
GPU 基础设施完备。真正 0 短路+精简 = 分层着色 + 解决 via/pin 隔离 (每层 via 用专属 x-track 下到 pin,或 pin 分配到各自层的正上方)。

### ★★★ 0 短路 + 精简 双达成 (2026-07-27, route_gpu.py CAP=1 分层) ★★★
alu1: **shorts=0, wires=1881, layers=29, 100s** (Win 5080)。我自己的 _short_cells 核验。
对比 route_channel (0短路/24915 wire) —— **精简 13 倍**,同时 0 短路。你要的两个目标同时达成。

关键突破点 (按顺序):
1. **CAP=1 分层**: 每个网独占一层 (trunk 在 layer color+1, layer 0 只放引脚)。
   1 网/层 => 层内短路**构造上不可能**。29 网 → 29 层, L=30。GPU 不在乎层数。
2. **y0 引脚平面隔离**: trunk 硬限制在专属层 (per-net cost, 非专属层 =BIG);y0 仅在
   该网 pin 列开放 via 竖直通道。消除了 653 个 y0 via 混叠短路。
3. **_short_cells 修正 (关键 bug)**: 原检测把相邻层索引 (dl=±1) 当短路,但层 y 间隔 2 +
   实心 support 隔离 (test_hv_layers Q2 验证) => 跨层根本不短。去掉层间 shift,只查层内
   8 邻域。这一步把假阳性 291→2→0。

route_gpu.py 完整流程: route_layered (冲突图 + CAP=1 着色) → route_layer_confined
(per-net 层限制 + y0 via 通道 + 层内 negotiated) → _short_cells 核验 0。
待验证: MCHPRS 逻辑真值表 (0 短路应=逻辑正确) + 游戏内建造。
可优化: 29 层电路高 (y=58);CAP>1 合并无冲突网可降层数,但需保证重路由不新增相邻。

### 下一步: GPU 布线 → 完整红石几何 → 验证 (工程管道,非算法)
GPU 布线输出 routes = {net: [(layer,gx,gz)]}(trunk 层坐标)。要接到 MCHPRS/建造需:
1. **几何发射**: 每网 trunk (专属层) 的 dust + support 块;via 火把塔从 trunk 层竖直下到
   y0 引脚 (每网 pin 列已在 route 里开了 via 通道);repeater 每 13 格刷新 (facing 规则已验证)。
   复用 build_from_route.py 的 typed placements 模式 + 火把塔几何 (test_vertical.py)。
2. **MCHPRS 真值表**: emit → nucleation Schematic → MchprsWorld → 40 向量。0 短路应 = 逻辑正确。
3. **游戏内建造**: build_verify.cjs (bot /setblock) — 但 29 层高电路,注意 210 格距离限制。
布线结构已可导出 (verify_gpu.py: 3762 块 for dust+support)。via 火把塔 + repeater 几何是
剩余接线工作。算法核心 (0 短路 + 精简 + GPU) 已完成。

---

## 六、关键文件

### redstone3d/ (布线器)
- `route_channel.py` — ChannelRouter, 全局网格 2 层曼哈顿, 0 短路/12x 膨胀 (当前最佳 0 短路版)
- `route_buildable.py` — BuildableRouter, 最短路 2 层, 1.0x/61 短路 (精简骨架, rip-up 基础)
- `route_tracks.py` — TrackRouter, 预留轨道 (弃, 749 短路)
- `build_from_route.py` — BuildResult→blocks (sim + bot 共用)
- `verify_buildable.py` — MCHPRS L1 验证器

### riscv_build/ (工具 + 探针 + 文档)
- `CHANNEL_SPEC.md` — 布线器完整验证几何规格
- `CPU_ROADMAP.md` — 完整 CPU 4 层缺口路线图
- `export_blocks.py` — synth→flat block-list JSON
- `build_verify.cjs` — bot 建造 + 驱动 PI + 读输出
- `lint_blocks.py` — 离线悬空/短路检测
- `verify_channel_mchprs.py` / `verify_module_mchprs.py` — MCHPRS 真值表验证
- `measure_2d.py` / `diag_route.py` — 布线诊断
- AGENT_A/B/C_*.py — bridge gadget / 隔离规则 / trunk 路由 (子任务产出)
- test_*.py / test_*.cjs — MCHPRS + 游戏内物理探针

### 验证阶梯
L1 MCHPRS (本地快, 相邻短路显现为错误输出) → L2 游戏内 alu1 →
L3 Control/Mux/ALU_Control/Imm_Gen → L4 Forwarding/ALU。
6 门 cell 游戏内验证不变;bug 纯在网间布线。

---

## 七、教训

- **子 agent 会谎报**: 两次把布线 bug 甩锅给 cell 库,均被证伪。永远用自己的 legality + 孤立 cell MCHPRS 复核,不信其"通过/根因"结论。
- **短路 = 功能错误,必须清零**;延迟/密度 = 性能,可接受。红石一处短路即整模块输出错。
- **局部修补搬运拥塞**: 全局耦合约束下,单点错开只是把短路移到别处(实测 197→1973)。
- **精简本身减短路**: 冗余布线(一列扩多列)= 更大相邻面 = 更多短路。最短路 = 少短路。
