# KERN 文档入口

本文区分当前实现、作者参考、待决事项和历史材料。架构事实以代码为准。

## 当前实现

- `current_architecture.md`：从当前代码整理的运行链、状态写入、主动阶段、事务和持久化边界。
- `package_composition.md`：Package 格式、扩展发现、runtime-scoped catalog 和 artifact identity。
- `failure_and_effect_record_contract.md`：ActionRejected、KernFailure、Event 和 Reaction 契约。
- `external_runtime_contract.md`：外部操作的 side-effect 分类、receipt 和生命周期回调。
- `开发者快速上手.md`：第一次运行 KERN 的最短路径和公开 runtime API。
- `配置详解.md`：当前代码实际读取的 runtime config 字段。

仓库根目录 `AGENTS.md` 是给代码 agent 的稳定边界和验证指导，不是产品文档或工作日志。

## 待决事项

- `kernel_backlog.md`：从已完成迁移计划中提取、并重新按代码复核的设计与质量缺口。

## 研究与通用参考

- `仿真模拟研究前沿综述_管理研究与KERN.md`：面向管理研究的仿真方法、近期 LLM agent 文献、验证要求与 KERN 选题建议。
- `仿真模拟研究前沿综述.md`：仿真与 LLM 主体文献综述，含证据边界与 KERN 定位。
- `风险信息传播案例调研.md`：研究案例素材，不代表当前可运行场景。
- `llm_gateway_server.md`：本地 LLM gateway 的运行说明。
- `scenario_authoring/LLMContext_*.md`：LLM provider 在运行时直接读取的 prompt 模板，不是历史文档。

## 归档

- `archive/legacy_scenarios/`：旧场景设计草稿或已暂停方向。它们可作为素材参考，但不是当前实现状态或开发路线图。
- `paper_research/`：论文和研究材料。该目录可能包含未跟踪的大量外部资料，不应在普通代码任务中顺手整理或提交。

当前可运行的回归 world Package 是 `Packages/Camping`。已移除的实验数据若需重建，应从
`research_data/` 中的原始资料开始，不应依赖历史 runtime 实现。
