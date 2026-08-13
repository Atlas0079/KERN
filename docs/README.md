# KERN 文档入口

本文区分当前实现、作者参考、待决事项和历史材料。架构事实以代码为准。

## 当前实现

- `current_architecture.md`：从当前代码整理的运行链、Package 组合、状态写入、主动阶段、事务、Event/Failure、外部 runtime 和持久化边界。
- `开发者快速上手.md`：第一次运行 KERN 的最短路径和公开 runtime API。
- `配置详解.md`：当前代码实际读取的 runtime config 字段。
- `野营场景设计.md`：Camping world Package 的当前场景目标、已实现行为、待补内容和移动建模待决项。
- `social_memory_design.md`：社交平台 Agent 可见记录与记忆机制的设计备忘；其中部分机制已经实现，未实现项以代码和实现状态文档为准。

仓库根目录 `AGENTS.md` 是给代码 agent 的稳定边界和验证指导，不是产品文档或工作日志。

## 待决事项

- `kernel_backlog.md`：从已完成迁移计划中提取、并重新按代码复核的设计与质量缺口。
- `social_platform_runtime_design.md`：社交平台的活跃设计、已实现/未实现状态、已知问题和验收计划；尚未冻结为稳定发布契约。
- `social_platform_experiment_plan.md`：海平面两条件实验的社交 workflow、活跃调度、兴趣映射、过程留痕和实施待办。

## 研究与通用参考

- `research/README.md`：调研资料的范围、可信度边界和主题索引。
- `research/simulation/仿真模拟研究前沿综述.md`：面向管理研究的仿真方法、近期 LLM agent 文献、合成消费者文献、验证要求与 KERN 选题建议。
- `research/social_platform/风险信息传播案例调研.md`：研究案例素材，不代表当前可运行场景。
- `llm_gateway_server.md`：本地 LLM gateway 的运行说明。
- `scenario_authoring/LLMContext_*.md`：LLM provider 在运行时直接读取的 prompt 模板，不是历史文档。

## 归档

- `archive/legacy_scenarios/`：旧场景设计草稿或已暂停方向。它们可作为素材参考，但不是当前实现状态或开发路线图。
- `paper_research/`：论文和研究材料。该目录可能包含未跟踪的大量外部资料，不应在普通代码任务中顺手整理或提交。

当前稳定回归 world Package 是 `Packages/Camping`。当前活跃实验链路还包含
`Packages/SocialPropagation` capability Package 和 `Packages/SeaLevelSocialExperiment` world
Package；它们属于社交平台实验方向，尚未冻结为通用稳定场景。已移除的历史实验数据若需重建，
应从 `research_data/` 中的原始资料开始，不应依赖旧 runtime 实现。
