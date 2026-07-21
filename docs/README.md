# KERN 文档入口

本文只列出当前实现、稳定契约和研究参考；历史场景草稿不再随仓库保留。

## 当前实现与后续事项

- 仓库根目录 `AGENTS.md`：稳定架构约束、当前迁移状态和验证命令。
- `scenario_package_migration_plan.md`：Package 组合、扩展发现、archive identity 与 runtime snapshot 的当前契约。
- `social_platform_runtime_plan.md`：SU7Crisis 社交平台危机传播的设计边界与实验方向。
- `runtime_composition_and_external_lifecycle_plan.md`：runtime 组合和外部 runtime 生命周期契约。

## 使用与研究参考

- `开发者快速上手.md`：第一次运行 KERN 的最短路径。
- `配置详解.md`：runtime config 字段和运行语义。
- `仿真模拟研究前沿综述_管理研究与KERN.md`：面向管理研究的仿真方法、LLM agent 文献、验证要求与选题建议。
- `仿真模拟研究前沿综述.md`：仿真与 LLM 主体文献综述，含证据边界与 KERN 定位。
- `风险信息传播案例调研.md`：可迁移为危机传播仿真的现实案例素材。

## 当前开发重心

ScenarioPackage 迁移已完成：一次运行选择一个世界包和零个或多个能力包；受信任的 Package 可声明 Effect、组件和 codec。archive/checkpoint 用版本化 runtime artifact identity 验证恢复输入；调试 snapshot 通过 ComponentCatalog 提供完整组件状态。

当前可运行场景是 Camping 与 SU7Crisis。SU7Crisis 使用 tick、reaction、effect 与 workflow 承载社交平台模拟：允许并行 LLM 决策，但所有 world commit 保持串行；下一步是补齐可复现实验曲线、干预策略、诊断和指标导出。
