# KERN 文档入口

本文用于区分当前主线文档、稳定参考文档和历史归档，避免后续开发时误把旧场景草稿当成当前路线图。

## 当前主线

- `agent_project_memory.md`：给 coding agent 的项目级记忆。记录稳定架构事实、当前约定和常用验证命令。
- `social_platform_runtime_plan.md`：社交平台 runtime 与 RumorSpread 谣言传播实验的当前说明。社交媒体相关工作优先看这里。
- `social_activity_parallel_decision_plan.md`：RumorSpread 批量并行 LLM 决策、串行提交的已实现设计说明。
- `crisis_management_ppt_worklog_20260709.md`：危机管理会议 PPT 的当日叙事工作台，记录主线、取舍、待补场景和验收标准。

## 通用参考

- `开发者快速上手.md`：第一次运行 KERN 的最短路径。
- `配置详解.md`：runtime config 字段说明。
- `effect_capability_inventory.md`：当前 43 个 Effect 的能力目录、分层和 DSL 边界审查。
- `scenario_package_migration_plan.md`：将场景数据、场景 Effect 和纯数据组件收敛为可独立加载场景包的分阶段实施计划。
- `Bundle结构查询与编辑辅助方案.md`：bundle 查询与编辑辅助方案。
- `动态文本一次性渲染设计.md`：动态文本渲染设计。

## 归档

- `archive/legacy_scenarios/`：旧场景设计草稿或已暂停方向。它们可作为素材参考，但不是当前实现状态或开发路线图。
- `paper_research/`：论文和研究材料。该目录可能包含未跟踪的大量外部资料，不应在普通代码任务中顺手整理或提交。

## 当前开发重心

当前主线是扩展 KERN 的 RumorSpread 社交平台实验：

1. 用现有 KERN tick / reaction / effect / workflow 架构承载社交平台模拟。
2. 通过 `SocialActivityGateTick` 控制社交行动机会。
3. 在 RumorSpread 场景中使用并行 LLM 决策、串行 world commit。
4. 基于已生成的 100-agent smoke 数据继续补齐可复现实验曲线和干预策略。
5. 可视化工具放在后期；当前优先建设诊断、指标导出和对比工具。
