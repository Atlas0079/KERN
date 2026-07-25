# Agent Workflow 主动阶段重构计划

状态：已实施并通过回归验证

## 目标

每个 simulation tick 保持两个阶段：

1. 被动阶段推进时间，发布 `WorldTickAdvanced` 和全部 `AdvanceTick`，并完成 Reaction FIFO；
2. 主动阶段由 KERN 选择可获得行动机会的 Entity，再由可替换的 Agent Workflow 决定是否行动以及下一条 ActionIntent。

主动阶段必须保持以下执行语义：

- KERN 每次只从 workflow 获取一条 ActionIntent 或 `EndTurn`；
- workflow 可以在 turn session 内一次生成多条指令，并自行保存计划和游标；
- 每条 ActionIntent 单独解析和提交；
- 当前 Action 的 EffectBundle 和全部 Reaction 结算完成后，workflow 才能提供下一条 Action；
- Action rejection 是可恢复的领域反馈；Effect、Reaction、workflow contract 或基础设施失败是 terminal `KernFailure`；
- workflow 不直接修改 `WorldState`。

## 模块职责

### KernRuntime

`KernRuntime` 只负责 tick 生命周期：建立本 tick 的 settlement、完成被动阶段、调用主动阶段。

### TurnScheduler

`KERN.sim.turn_scheduler` 负责系统调度：

- 按稳定顺序建立 controller 候选；
- 检查 Entity、controller 和 wake policy；
- 生成 `TurnStart`；
- 选择对应 workflow 并把 turn 交给 `TurnRunner`。

TurnScheduler 不属于 Agent Workflow。

### TurnRunner

`KERN.sim.turn_runner` 负责一个 turn 的系统执行状态机：

- action/replan budget；
- 构造结算后的 `DecisionFrame`；
- 请求 workflow 的下一步；
- ActionIntent 解析、提交和 Reaction 结算；
- rejection 记录与反馈；
- abort、controller 失效和长任务开始后的停止条件。

### AgentWorkflow 与 AgentTurnSession

`AgentWorkflow.begin_turn(TurnStart)` 创建 turn-scoped session。`AgentTurnSession.next_step(DecisionFrame)` 返回 `SubmitAction` 或 `EndTurn`。

Session 可以保存 LLM 一次生成的 Action 列表、当前游标和 rejection 历史。Session 只存在于同步主动阶段；当前 checkpoint 在完整 tick 结束后写入，因此 session 不进入 checkpoint。跨 turn 状态必须通过 Effect 写入 WorldState，或进入显式 external runtime。

## 实施顺序

1. 用行为测试锁定被动阶段先于主动阶段、逐 Action Reaction 结算、rejection 重规划、task/abort 停止和 terminal failure；
2. 新增 workflow contract、turn session 和旧 `action_plan` provider Adapter；
3. 将 TurnScheduler 移至 `KERN.sim`，拆出 TurnRunner；
4. 将决策输入构造集中到 `DecisionContextBuilder`；
5. 将 ActionIntent 解析从 `agent_workflow.runtime` 移至 `KERN.interaction`；
6. 让内置 SimplePolicy 和 LLM provider 通过 session Adapter 运行；
7. 增加 runtime-scoped workflow registry 和第三方装配入口；
8. 更新开发者文档，删除旧接口的主线描述；
9. 运行聚焦测试、全量 unittest、compileall、scenario lint 和 camping smoke runtime。

## 兼容策略

现有实现 `decide(ws_view, recipe_db, actor_id, reason, mode_context) -> action_plan | end_turn` 先由 Adapter 包装。Adapter 在 session 内保存 plan 尾部：成功后继续下一项，rejection 后丢弃尾部并重新调用 provider。主循环不再保存 provider 的计划游标。

旧模块路径 `KERN.agent_workflow.turn_scheduler` 暂时保留只读导入 shim；新代码和文档统一使用 `KERN.sim.turn_scheduler`。

## 验收条件

- `KernRuntime` 不再从 `KERN.agent_workflow.turn_scheduler` 导入调度器；
- TurnScheduler 不再执行 ActionIntent 或维护 plan/replan 循环；
- 多 Action 计划在每项之间完整结算 Reaction；
- rejection 作为 `ActionFeedback` 返回同一个 turn session；
- bundle/reaction/provider 异常使 runtime terminal；
- SimplePolicy、LLM provider 和自定义测试 workflow 都能通过同一 session seam 运行；
- checkpoint 与 event/action ID 的现有行为保持不变。
