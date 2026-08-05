# 代码审查与可行性验证材料 — RISC-V 红石布线器

> 供 claude-opus-5 在新会话审查使用。目标：审查 `route_buildable.py` 泛化质量劣化问题，
> 并验证"placer 重排"方案可行性。
> 当前会话（deepseek）已切换 provider 至 lmuai（claude-opus-5），新会话即生效。

## 1. 项目背景

把 RISC-V 8-bit CPU 模块（ujjwal-2001/RISCV_8bit_pipeline 的 Verilog）综合成门级网表，
再用自研布线器把每个模块布成 **Minecraft 红石电路**（y0 信号平面 + 高层/地下 cross 平面 + 竖直塔），
产出可直接 /setblock 建造的 block 列表。

验证链：MCHPRS 物理模拟（真实红石物理）→ 链路电气验证（每 net 驱动 1/0 读 sink）→ 游戏内建造。

## 2. 代码位置与审查对象

```
mcp-server/scripts/redstone3d/
  route_buildable.py   ← 核心布线器（约 1000 行，重点审查对象）
  placer.py            ← 布局器（gate 拓扑列 + PI 注入，刚做过 PI 对齐重排）
  via_gadget.py        ← 竖直传输原语（UP 1×1 塔 / DOWN 2×2 塔 / rise / drop）
  verify_links.py      ← 链路电气验证（驱动 source 读 sink，响应式判定）
  build_from_route.py  ← 布线结果 → block 列表
  test_generalize.py   ← 全模块泛化测试
  diag_placement.py    ← 布局诊断
mcp-server/scripts/riscv_build/
  ROUTER_JOURNAL.md    ← 完整技术日志（§I-§X，含已证伪路径）
  test_*.py            ← 各原语 MCHPRS 验证
```

## 3. 当前指标（alu1，24 门 29 net）

| 指标 | 值 |
|------|-----|
| 短路 | 0（rep-aware 检测，repeater 只前后导通已实测） |
| 布通 | 24/29 |
| 链路电气验证 | 24/24 全通（响应式：drive1>drive0） |
| wires | 2499（Manhattan 比 0.87） |
| 塔 | UP 1×1 塔 + DOWN 2×2 塔（MCHPRS 全验证，非反相、无衰减、可旋转） |

## 4. 泛化测试结果（质量随规模劣化 ← 核心问题）

| 模块 | 门数 | net | 布通率 | 短路 | wires |
|------|------|-----|--------|------|-------|
| alu1 | 24 | 29 | 83% | 0 | 2499 |
| Control | 22 | 25 | 80% | **2** | 2532 |
| Mux2to1 | 25 | 34 | 71% | **1** | 3974 |
| ALU_Control | 31 | 40 | 73% | 0 | 3921 |
| ImmGen | 32 | 41 | 83% | 0 | 9061 |
| Forwarding | 92 | 112 | **59%** | **54** | 20935 |
| ALU | 197 | ? | 后台跑中 | ? | ? |

模式：小模块 71-83% 布通；92 门掉到 59% 且短路 54（短路清零也没泛化）。

## 5. alu1 剩 5 net 未布通的原因（诊断）

- 全是最长连接（174-257 格），top-8 最长连接占曼哈顿总长 48%
- 静态空间充裕（sink 西向净空 15-40 格），失败纯因**先布 net 抢占通道**
- 失败类别几乎全是 "DESCENT conflict"（sink 侧下降走廊被占）

## 6. 已证伪路径（勿重复，详见 ROUTER_JOURNAL §X）

1. descent 走廊扩大候选（更多 z 偏移 + x 后退）→ 5 failed 变 8
2. LONG_HAUL 长连接强制上 cross 层 → 布通 24→26 但链路仅 16/26（长 cross 电气可靠性差）
3. 地下 cross 平面（cross 移到 y<0）→ 物理验证全通但布通率 8 vs 5（塔只能向上，两侧总有一侧需楼梯）
4. DOWN 塔优先于楼梯 → failed 5→8（塔占 feed 周围 4 列，此布局空行比空 2×2 易得）；塔作**兜底**后恢复 5
5. negotiated rip-up（软重叠）→ 短路爆炸 310；硬约束 + 失败优先 → 微改进但带短路
6. 缩小 col_gap（16→6-12）→ wires 大降但布通率降或有短路

## 7. 已做的重排（净收益）

- **PI 按消费者 z 中位数放置**（旧版机械阶梯，n8 的 PI 在 z=96 消费者在 z=19）
  → bbox z 97→62，曼哈顿 3285→3033，wires 2868→2499（-13%），短路仍 0，布通率不变
- 但最长连接仍 244 格——是 **x 方向**跨越（PI x=0 → 深层 gate x=225），由拓扑深度×col_gap 决定

## 8. 待审查/验证的问题清单

A. **泛化质量劣化根因**：为什么规模大了布通率掉、短路出现？是布线器算法问题（贪心无 rip-up、
   bridge 几何太脆），还是布局问题（狭长 bbox：Forwarding 177×820）？

B. **placer 重排方案可行性**（下一步候选）：
   1. PI 复制/缓冲（深层 gate 的 PI 输入中途插 BUF 分段）——缩短 x 向长连接？
   2. 列折叠（蛇形排列代替单向 +x）——压缩 bbox x 宽？
   3. 列内 cell 按连接关系排 z（连同一 net 的 gate 靠近）？
   4. col_gap 自适应（按该列实际出线数）？
   请评估各方案的收益/风险/实现复杂度，给出推荐。

C. **布线器算法层面**：贪心 BFS + 局部 bridge 是否可替换为更稳健的全局方法？
   （注：GPU negotiated 布线器 route_gpu.py 已在 Win 存在且抽象层 0 短路，但抽象→真实几何
   的鸿沟导致 emit 后 stuck-high，见 ROUTER_JOURNAL §VIII-IX）

D. **MCHPRS 整芯片真值表验证慢**（每向量重建 40000+ blocks，60s/8向量）——有没有加速办法？
   （如：单次建 world 后改注入重 tick？或分块验证？）

E. **正确性风险**：verify_links 的响应式判定（drive1>drive0）在完整电路（29/29 布通）下
   是否仍有意义？MCHPRS 与真实 MC 服务器物理是否有差异需要游戏内复验？

## 9. 设备/运行事实

- 布线运算（GPU/torch）在 Win（E:\py312\python.exe, RTX 5080, ssh yd.frp-one.com:59325）
- MCHPRS 模拟按用户指令移交给 Win 执行
- Mac 可跑纯 CPU 布线 + 小规模 MCHPRS
- 用户原则：不接受未验证修复；算法要**泛化**（不针对 alu1 硬编码）；布线要**最大化精简**
  （一列能过的不要扩成多列）
