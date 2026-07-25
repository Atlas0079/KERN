# KERN 文档入口

本文用于区分当前主线文档、稳定参考文档和历史归档，避免后续开发时误把旧场景草稿当成当前路线图。

## 当前实现与后续事项

- 仓库根目录 `AGENTS.md`：给 Codex 的项目级指导。记录稳定架构约束、当前迁移状态和验证命令；它不是工作日志。
- `scenario_package_migration_plan.md`：Package 组合、扩展发现、archive identity 与运行时 snapshot 的当前契约。
- `runtime_composition_and_external_lifecycle_plan.md`：已实施的 runtime 组合和外部 runtime 生命周期契约；其下一阶段仍需单独规划。
- `turn_action_reaction_design.md`：Turn、Action、Effect/Event、Reaction、同 tick rejection 重试及 interaction 感知的目标设计；其中感知 inbox 已实施，TurnScheduler 和统一 Event 模型尚未实施。
- `architecture_followup_p2.md`：尚未实施的 Package 扩展模块进程级缓存事项及其触发条件。

## 通用参考

- `开发者快速上手.md`：第一次运行 KERN 的最短路径。
- `配置详解.md`：runtime config 字段说明。
- `仿真模拟研究前沿综述_管理研究与KERN.md`：面向管理研究的仿真方法、近期 LLM agent 文献、验证要求与 KERN 选题建议。
- `仿真模拟研究前沿综述.md`：仿真与 LLM 主体文献综述，含证据边界与 KERN 定位。

Effect、组件 codec 和动态文本的稳定约束已浓缩到
`AGENTS.md`；对应的已完成设计原文不再保留。

## 归档

- `archive/legacy_scenarios/`：旧场景设计草稿或已暂停方向。它们可作为素材参考，但不是当前实现状态或开发路线图。
- `paper_research/`：论文和研究材料。该目录可能包含未跟踪的大量外部资料，不应在普通代码任务中顺手整理或提交。

## 当前开发重心

ScenarioPackage 迁移已完成：一次运行选择一个世界包和零个或多个能力包；受信任的
Package 可声明 Effect、组件和 codec。archive/checkpoint 用版本化 runtime artifact identity
验证恢复输入；调试 snapshot 通过 ComponentCatalog 提供完整组件状态。

当前可运行的回归世界包是 `Packages/Camping`。已移除的实验数据若需重建，应从
`research_data/` 中的中性原始资料开始，不应依赖历史 runtime 实现。
