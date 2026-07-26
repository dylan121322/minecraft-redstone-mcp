# 调研结论：nucleation/redpiler create 慢 —— 非 bug，是我方布线缺陷

**最初怀疑**：`MchprsWorld.create_with_options` 在小电路上慢（3 门 create 5s），
`export_graph_structural()` 显示 89 节点却 51145 边，疑似 redpiler 性能 bug。

**深入调研后的诚实结论：不是 nucleation 的 bug。** 逐项排除：

| 假设 | 实测 | 结论 |
|------|------|------|
| wire 数多导致慢 | 300 段红石线 create 0.01s | 否 |
| repeater 导致边爆炸 | repeater vs wire 在同布局边数相同 | 否 |
| torch 密度导致慢 | 300 独立火把 create 0.01s | 否 |
| 255-default-input 硬限制 | 300 火把 opt=False 正常 | 特定连通结构才触发，非普遍 |
| **密集红石粉 O(N²) 边** | N×N 实心 dust 块边数 ≈ N²（9→81, 121→14116） | **是语义正确行为**：Minecraft 里实心 dust 块确实全互连 |

**真正的慢来自我方布线器的缺陷**（均已修复）：
1. 悬空红石线（下方无支撑）→ redpiler 异常。修：每 wire 下加支撑 + 垂直移动重惩罚强制平面。
2. 对角 ramp 短路（不同 net 斜连）→ 连通图污染。修：keep-out 查对角。
3. 密集绕路（rip-up + 过度垂直惩罚）→ 大量平行 dust 相邻 → O(N²) 边。修：垂直惩罚降到 6。

修复后：3 门 create 5s→2.8s、边 51145→2735；无悬空/短路时 nucleation 表现正常。

**不提 PR** —— 证据不支持报 bug。O(N²) 边是密集 dust 的固有语义，redpiler 处理无误。
应做的是**布线器减少 dust 密度**（更短路径、留间距），这是我方优化项。

**给 nucleation 的正向反馈（可选，非 bug）**：`export_graph_structural()` 的
node/edge 计数对诊断布线密度非常有用，是很好的 API。密集 dust 的 O(N²) 边可
在文档里提示用户（布线密集时图会变大），但不是缺陷。
