# KERN 文档入口

本文用于区分当前主线文档、稳定参考文档和历史归档，避免后续开发时误把旧场景草稿当成当前路线图。

## 当前主线

- 仓库根目录 `AGENTS.md`：给 Codex 的项目级指导。记录稳定架构约束、当前迁移状态和验证命令；它不是工作日志。
- `scenario_package_migration_plan.md`：ScenarioPackage 的剩余实施路线，当前下一步是数据型场景包加载。
- `social_platform_runtime_plan.md`：社交平台 runtime 与 RumorSpread 谣言传播实验的当前说明。社交媒体相关工作优先看这里。

## 通用参考

- `开发者快速上手.md`：第一次运行 KERN 的最短路径。
- `配置详解.md`：runtime config 字段说明。
- `仿真模拟研究前沿综述_管理研究与KERN.md`：面向管理研究的仿真方法、近期 LLM agent 文献、验证要求与 KERN 选题建议。
- `仿真模拟研究前沿综述.md`：仿真与 LLM 主体文献综述，含证据边界与 KERN 定位。

Effect、组件 codec、动态文本和 RumorSpread 并行决策的稳定约束已浓缩到
`AGENTS.md`；对应的已完成设计原文不再保留。

## 归档

- `archive/legacy_scenarios/`：旧场景设计草稿或已暂停方向。它们可作为素材参考，但不是当前实现状态或开发路线图。
- `paper_research/`：论文和研究材料。该目录可能包含未跟踪的大量外部资料，不应在普通代码任务中顺手整理或提交。

## 当前开发重心

当前内核主线是完成 ScenarioPackage 迁移：先支持独立数据场景，再在显式授权下加载
受信任的场景 Effect、组件和 codec，并让 archive 校验场景身份与版本。

RumorSpread 社交平台实验继续作为现有的真实场景和验证对象：

- 使用现有 tick / reaction / effect / workflow 架构承载社交平台模拟。
- 通过 `SocialActivityGateTick` 控制社交行动机会。
- 并行 LLM 决策、串行 world commit。
- 后续补齐可复现实验曲线、干预策略、诊断和指标导出。
