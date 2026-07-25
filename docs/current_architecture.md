# KERN 当前架构

本文描述当前代码的运行边界。实现与本文冲突时，以 `KERN/` 下的实现为准。

## 1. 权威运行链

```text
runtime config / Package selection
-> LoadedPackages + DataBundle + frozen catalogs
-> build or restore WorldState
-> passive tick settlement
-> active turns and Agent Workflow
-> ActionIntent compilation
-> EffectBundle transaction
-> committed Events and Reaction FIFO
-> runtime snapshots, archives, and failure evidence
```

`KernRuntime.from_config()` 是主要装配入口。顶层 `packages` 由 Package loader 解析，
`env` 由 runtime 和 provider 读取。装配过程完成以下工作：

1. 选择且只选择一个 world Package，并加载零个或多个 capability Package；
2. 建立本次运行独有的 `EffectCatalog` 和 `ComponentCatalog`，注册所选 Package 的扩展并冻结；
3. 加载组合后的 world、entity、recipe、reaction 和 named bundle 数据；
4. 校验数据，随后构建 `WorldState`，或验证 Package identity 后恢复 checkpoint；
5. 装配 executor、interaction engine、workflow registry、reaction system、archive 和 failure writer。

Package 格式、扩展发现与 artifact identity 见 `package_composition.md`。

## 2. 状态与行为边界

`WorldState` 保存权威世界状态。Component 表达实体状态和能力；Effect 与系统表达行为。

- workflow、decision、recipe 和 reaction 只能读取视图并产生意图或 EffectBundle；
- Binder 在 Handler 运行前校验并规范化 Effect 输入；
- `WorldExecutor` 是世界写入和事务回滚边界；
- `WorldSettlement` 只发布已经提交的 Event，并驱动 Reaction；
- archive、snapshot 和 failure report 观察执行结果，不决定世界行为。

`WorldState.services` 仍是 runtime 每 tick 注入的兼容依赖袋。当前 runtime 使用它提供
interaction engine、workflow registry、provider、external runtime bridge、view profile、
stop callback 和 settlement execute callback。它是现存接口，不是新增任意依赖的入口。

## 3. Tick 与主动阶段

`KernRuntime.step()` 每次建立新的 `WorldSettlement`，并按固定顺序执行：

1. 重置本 tick 的 trigger 状态和 `RuntimeState`；
2. 推进 game time，发布 `WorldTickAdvanced` 并结算其 Reaction FIFO；
3. 按 Entity ID 排序发布全部 `AdvanceTick`，结算被动 Reaction FIFO；
4. 若没有 abort，由 `KERN.sim.turn_scheduler.TurnScheduler` 进入主动阶段。

TurnScheduler 只负责授予 turn：它按稳定顺序查找启用 controller 的实体，检查
`AgentWakePolicyComponent` 和 interrupt rules，解析 runtime-scoped workflow，然后交给
`TurnRunner`。

`TurnRunner` 负责单个 turn 的系统状态机：

```text
TurnStart
-> workflow.begin_turn()
-> build DecisionFrame from current settled state
-> session.next_step()
-> EndTurn
   or SubmitAction
      -> resolve ActionIntent
      -> ActionRejected feedback
         or execute one top-level EffectBundle and settle all Reactions
-> build the next DecisionFrame
```

一个 workflow session 可以保存多步计划，但每次只能提交一条 ActionIntent。每条 Action
单独解析和提交，前一条 Action 的 Reaction FIFO 清空后才会请求下一条。合法但不可执行的
动作是 `ActionFeedback(status="rejected")`；provider、contract、Effect 或 Reaction 失败是
terminal `KernFailure`。action 和 replan 数量分别受 runtime budget 限制。

## 4. Bundle、Event 与 Reaction

一个 EffectBundle 是一个世界事务。Executor 在执行前验证 Effect ID 和外部副作用顺序，
为最外层 Bundle 建立 transaction ID，并保存 `WorldState` 快照。任何 Effect 或 child bundle
失败都会恢复包含它的事务快照。

`InvokeBundle`、`RandomBundle`、`ApplyToQuery` 和 Task lifecycle 等 child bundle 与父 Bundle
共享事务。它们产生的 Event 在最外层 Bundle 成功前不会交给 Reaction。

成功 Effect 产生统一 Event envelope，其中保存 Binder 规范化输入、执行上下文、payload、
`bundle_id`、`parent_bundle_id`、`action_id` 和 `effect_index`。Handler 的 custom Event 保持原顺序，
随后追加默认的 Effect-ID Event。Settlement 提交这些记录后，Reaction 才能消费它们。

Reaction 使用确定性 FIFO：同一 Event 的规则按配置顺序执行，新 Event 追加到队尾。每个
Reaction Bundle 是新的事务；此前成功的 Reaction 不因后续 Reaction 失败而回滚。深度超限、
绑定失败或执行失败都会抛出 `KernFailure` 并终止 runtime。

更完整的失败和 Event 字段见 `failure_and_effect_record_contract.md`。

## 5. 组件转换与持久化

`ComponentCatalog` 是 template JSON、live component 和 checkpoint JSON 之间的统一转换边界。
构建、override、动态创建实体、archive、restore 和 lint 使用同一个 runtime catalog。

- 已注册组件必须通过自己的 codec 往返；
- 未注册组件按 `CustomComponent(data=...)` 保持兼容；
- catalog 在 runtime 执行前冻结；
- checkpoint 保存组件数据和 Task lifecycle bundle，不保存 Python Handler 或 catalog 对象。

持久化输出分为三个用途：

- `KernRuntime.snapshots`：`runtime_snapshot.v2` 调试快照，`component_state` 是完整 catalog 序列化状态；
- run archive：`run_archive.v1` manifest、周期 snapshot 和逐 tick delta，可重建指定 tick；
- `failure.json`：一次 runtime 的开发者失败证据，与世界 checkpoint 和事务分离。

archive 和 checkpoint 写入 `package_identity.v2`，恢复时验证所选 Package 的实际加载 artifact。

## 6. 外部状态边界

外部系统不属于 `WorldState` 快照，世界回滚不能撤销已经发生的外部写入。扩展 Effect 必须
通过 `EffectSpec.side_effect` 声明 `world`、`external_transactional`、
`external_compensatable` 或 `external_irreversible`。Executor 与 `ExternalRuntimeBridge` 负责
receipt、commit、rollback 和 checkpoint 生命周期通知。详细契约见
`external_runtime_contract.md`。

## 7. 模块所有权

| 模块 | 当前责任 |
| --- | --- |
| `KERN/runtime.py` | runtime 装配、tick 生命周期和记录输出 |
| `KERN/package.py` | Package 选择、数据组合、扩展注册和 catalog 冻结 |
| `KERN/data/` | 数据加载、世界构建、checkpoint 和 archive |
| `KERN/component_catalog/` | ComponentSpec、codec 和转换 catalog |
| `KERN/effects/` | EffectSpec、core definitions 和 effect catalog |
| `KERN/executor/` | Binder、Handler、Bundle 事务和世界回滚 |
| `KERN/interaction/` | Recipe 匹配和 ActionIntent 编译 |
| `KERN/sim/` | Reaction settlement、turn 调度和 turn 执行 |
| `KERN/agent_workflow/` | 决策视图、记忆 patch、workflow contract 和 provider adapter |
| `KERN/query/` | condition predicate 和路径解析 |
| `KERN/external_runtime.py` | 外部 adapter 路由与生命周期协议 |
| `KERN/failure_report.py` | 单次 runtime 的失败证据 |

