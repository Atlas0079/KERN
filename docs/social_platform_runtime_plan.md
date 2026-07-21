# 社交平台危机传播设计

> 状态：当前设计参考。可运行场景为 `Packages/SU7Crisis`；本文件只保留稳定的设计思路和边界。

## 目标

KERN 将危机传播建模为公开信息、平台分发、主体决策和干预之间的可审计交互。它不判断现实事故责任或替代事实调查；它模拟不同主体如何接触、解释、互动和回应已提供的信息。

## 分层

```text
SU7Crisis Package data
-> KernRuntime / WorldState
-> workflow perception and decision
-> InteractionEngine command compilation
-> effect bundle
-> WorldExecutor world transaction
-> SQLite social-platform runtime
-> archive, checkpoint, and analysis tools
```

- 世界包提供实体、recipes、reactions、社交 seed 与运行所需数据。
- workflow 只读取裁剪后的视图并返回 command，不直接写世界或数据库。
- `InteractionEngine` 将 command 匹配为 effect bundle；`WorldExecutor` 是唯一的 `WorldState` 写入入口。
- SQLite runtime 负责账号、帖子、互动、推荐与屏幕上下文等平台状态；它通过显式 domain effect 接入 KERN。

## 一致性与事件语义

- 一个 effect bundle 是一个 `WorldState` 事务；其任一 effect 失败会回滚整个 bundle。
- bundle 的成功事件仅在提交后由 `WorldSettlement` 按 FIFO 顺序发布并触发 reactions。
- child bundle 属于外层 transaction；其事件同样等待最外层成功提交。
- 外部 runtime 不自动参与 `WorldState` 回滚。涉及外部写入的 bundle 应保持短小，并把不可逆外部 effect 放在其他可失败 effect 之后。
- 外部 runtime 生命周期失败会终止运行，避免在状态不确定时继续推进。

## 主体调度与可重复性

`SocialActivityGateTick` 决定哪些主体获得一次社交行动机会。主体是否浏览、打开、评论、转发或发帖仍由其 workflow 决定。

LLM 场景可以并行执行 `decide(...)`，但候选准备、command 校验、effect 执行和世界提交始终按稳定顺序串行进行。工作线程不得写 `WorldState` 或调用 `WorldExecutor`。

社交 workflow 使用 `social_platform` view profile，避免同地点的物理实体和无关事件污染 prompt；手机屏幕中的可见内容是社交行动的主要 grounding 上下文。

## 实验方向

可比较的信息策略包括：不同回应时机、技术解释与情绪回应的组合、第三方解释、平台提示和分发调整。评估应基于 archive 与社交 SQLite 的原始记录，例如曝光、打开、互动、信息触达和讨论焦点随 tick 的变化。

后续工作应以可复现实验为目标：明确干预模型、导出指标、定义 baseline 与对照组，并验证结论在不同 seed 和主体配置下的稳健性。

## 相关实现

- `Packages/SU7Crisis/`：当前世界包与社交 seed。
- `KERN/external_runtimes/social_platform.py`：SQLite 平台 adapter。
- `KERN/executor/_effect_social_platform.py`：社交 domain effects。
- `KERN/executor/_effect_social_activity.py`：社交行动调度。
- `KERN/agent_workflow/view_profile.py`：workflow 视图裁剪。
- `tests/test_social_*.py`、`tests/test_workflow_view_profile.py`：核心行为覆盖。
