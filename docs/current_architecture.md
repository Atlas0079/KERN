# KERN 当前架构与内核契约

本文描述当前代码的运行边界和稳定契约。实现与本文冲突时，以 `KERN/` 下的实现为准。

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
5. 装配 executor、interaction engine、workflow registry、reaction system、archive、failure writer
   和已选择的 external runtime 实例。

workflow provider 是源码内置实现集合，不是 Package 自动发现项。runtime config 可以通过
`workflow_providers` 选择 `KERN.agent_workflow.builtin_workflows.BUILTIN_WORKFLOW_BUILDERS`
中注册的 kind；开发者新增 workflow 时需要修改源码注册表和对应 builder。当前内置 kind 包括
`simple`、`llm` 和 `social_platform`。

workflow builder 属于内核装配层。`simple` builder 返回无 LLM 策略；`llm` builder 包装旧有
`llm_providers` / `workflows` role 配置；`social_platform` builder 读取已加载 world Package
中的 study data，构造内置 `KERN.agent_workflow.social_platform.SocialPlatformWorkflow`。Package
data 可以为内置 workflow 提供场景事实，但 workflow 实现本身不通过 Package loader 自动注册，
KERN 内核也不 import capability Package 的 workflow 代码。

Package 路径必须位于 project root 内，Package ID 不得重复。manifest 文件固定为 Package
根目录的 `kern-package.json`。world Package 必须声明 `provides_world: true` 和完整 world
data；capability Package 不能提供 world 文件，但可以组合 recipe、reaction、named bundle、
Effect、Component 和 codec。

有扩展代码时，入口固定为 Package 根目录的 `extensions.py`：

```python
EFFECT_MODULES = ("effects.weather",)
COMPONENT_MODULES = ("components.weather",)
EXTERNAL_RUNTIME_MODULES = ("runtimes.weather",)
```

loader 只导入入口声明的 Package-local 模块，并只注册其中带 `@package_effect` 或
`@package_component`、`@package_external_runtime` 标记的定义。组件和 codec 先注册，Effect
后注册，外部 runtime provider 也进入本次 runtime-scoped catalog。Package definition ID
必须使用所属 Package 的命名空间。

Package 装配完成后生成固定的 `package_identity.v2`。identity 只覆盖本次 runtime 实际读取
或导入的 artifact：

- 每个选中 Package 的 `kern-package.json`；
- 实际加载的 world、entity、recipe、reaction 和 bundle JSON；
- 已声明的 `extensions.py` 和实际导入的 Package-local Python 模块；
- 冻结后的 Effect ID、Component ID 和 external runtime provider ID 清单；
- runtime config 选择的 external runtime instance ID、provider 和 options。

已加载 artifact 或 external runtime instance 配置改变时，v2 checkpoint 恢复会失败。历史 v1
identity 和缺少 Package metadata 的 checkpoint 会被拒绝。当前稳定回归 world Package 是
`Packages/Camping`；社交平台实验还使用 `Packages/SocialPropagation` capability Package 和
`Packages/SeaLevelSocialExperiment` world Package。历史归档场景不参与 Package 加载。

普通 Package Component 必须是纯数据 dataclass，默认使用 `DataclassCodec`。需要特殊转换时，
Package 必须显式提供 codec。

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
-> workflow.begin_turn(ws, start)
-> build TurnFrame with scheduling state and prior action feedback
-> session.next_step(ws, frame)
-> EndTurn
   or SubmitAction
      -> resolve ActionIntent
      -> ActionRejected feedback
         or execute one top-level EffectBundle and settle all Reactions
-> build the next TurnFrame
```

一个 workflow session 可以保存多步计划，但每次只能提交一条 ActionIntent。每条 Action
单独解析和提交，前一条 Action 的 Reaction FIFO 清空后才会请求下一条。合法但不可执行的
动作是 `ActionFeedback(status="rejected")`；TurnRunner 会把 rejection 作为
`interaction_origin="action_rejection"` 的 `RecordInteraction` 写入 interaction log，但它不是错误
Event，也不进入 Reaction FIFO。provider、contract、Effect 或 Reaction 失败是 terminal
`KernFailure`。action 和 replan 数量分别受 runtime budget 限制。

`TurnFrame` 不包含 perception 或 action catalog。每次调用时 workflow 直接读取当前 `ws`，
自行决定需要哪些组件并构造领域感知；workflow 不得直接修改 `WorldState`，写入仍只能通过
返回的 ActionIntent 编译为 EffectBundle 后由 executor 提交。默认 LLM workflow 内部使用
自己的 observer 和 memory policy；其他内置 workflow 可以直接读取当前 runtime 已加载的核心
或 Package 组件。

对话使用独立的 `DialoguePolicy` seam。`StartConversation` 在单个 tick 内建立稳定参与者顺序，
先只读世界并生成有界 transcript；全部 provider 调用成功后，再通过一个 child bundle 将每句
发言写成 `RecordInteraction(verb="Say")`。每句发言进入 `interaction_log` 和同地点 Agent 的
`interaction_inbox`。机器 Event 只保留 `InteractionRecorded`、`ConversationCompleted` 和默认
`StartConversation` 记录。任意 provider 或 interaction 写入失败都会使整段对话不留下部分状态。

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

`ActionRejected` 表示 Decision 产生的意图符合 schema，但当前世界没有可执行路径，例如没有
匹配 Recipe、目标不存在或 condition 不满足。它是正常 Action 结果，不写错误 Event，不终止
runtime，也不进入 Reaction FIFO。当前 TurnRunner 会为它写一条 rejected interaction，供审计和
Agent feedback 使用。

`KernFailure` 表示 KERN、Package、Provider 或运行环境未能履行契约。稳定字段包括：

```text
code
message
origin
phase
context
cause / traceback
```

Executor、Binder、Workflow、Reaction、Persistence 和 External runtime 的 Failure 都通过
Python exception 传播。Bundle 在异常路径恢复快照，Runtime 在公开执行入口捕获第一次
Failure，并最多写一份 `<checkpoint_dir>/failure.json`。报告保留完整开发者证据，包括原始异常链、
traceback、规范化 Effect 输入、Decision、LLM 上下文和执行身份；报告写入失败不会覆盖原始
Failure。报告按当前产品策略不脱敏，会保留完整 runtime config，包括凭据；调用方必须把
`failure.json` 当作敏感运行产物管理。

Recipe 和 Reaction 只有在定义 `narrative_success` 时，才由编译器自动生成一条 interaction
记录。作者仍可在 Bundle 中显式放置任意数量的 `RecordInteraction`；交互是否重复由 Bundle
作者负责。`RecordInteraction` 写入时一次性提供交互文本和可感知数据，Handler 根据交互发生时
的世界状态确定感知者，并把包含 `tick`、`time_str` 和 `interaction_id` 的快照写入
`PerceptionComponent.interaction_inbox`。该写入与 interaction log 属于同一个 Bundle 事务。

EffectBundle 还可以声明 `record: {"mode": "auto", "target": "self"}`。此模式会在 bundle 成功后
调用各 Effect 的 recorder，把 Agent 可见片段写入行动者的 record inbox。`record.mode="template"`
目前只在结构层保留，executor 会以 `BUNDLE_RECORD_TEMPLATE_UNSUPPORTED` 拒绝执行。

## 5. 组件转换与持久化

`ComponentCatalog` 是 template JSON、live component 和 checkpoint JSON 之间的统一转换边界。
构建、override、动态创建实体、archive、restore 和 lint 使用同一个 runtime catalog。

- 已注册组件必须通过自己的 codec 往返；
- 未注册组件按 `CustomComponent(data=...)` 保持兼容；
- catalog 在 runtime 执行前冻结；
- checkpoint 保存组件数据和 Task lifecycle bundle，不保存 Python Handler 或 catalog 对象。

持久化输出分为三个用途：

- `KernRuntime.snapshots`：`runtime_snapshot.v2` 调试快照，`component_state` 是完整 catalog 序列化状态；
- run archive：`manifest.json` 使用 `run_archive.v1`；周期 snapshot 使用 `run_snapshot.v1`；
  逐 tick delta 使用 `run_delta.v1`，可重建指定 tick；
- `simulation_log.json`：`simlog.v1`，合并 event log 和 interaction log，restore 时可作为历史日志来源；
- `failure.json`：`kern_failure.v1`，一次 runtime 的开发者失败证据，与世界 checkpoint 和事务分离。

显式启用 `LLM_TRACE_MODE=full` 时，runtime 还会在 checkpoint 输出目录旁写入独立的压缩
LLM trace。trace 不属于 `WorldState` 或 checkpoint，可以按 tick 和 Agent 查看精确请求、输出
及 Action feedback。

archive 和 checkpoint 写入 `package_identity.v2`，恢复时验证所选 Package 的实际加载 artifact。
restore 优先读取同 run_id 的 `simulation_log.json` 作为历史 event/interaction log；不可用时才退回
snapshot 内携带的当前 tick log。

## 6. 外部状态边界

外部系统不属于 `WorldState` 快照，世界回滚不能撤销已经发生的外部写入。扩展 Effect 必须
通过 `EffectSpec.side_effect` 声明 `world`、`external_transactional`、
`external_compensatable` 或 `external_irreversible`。

| 值 | 语义 |
| --- | --- |
| `world` | 只写 `WorldState` |
| `external_transactional` | adapter 拥有真正的回滚能力 |
| `external_compensatable` | adapter 使用 receipt 执行补偿 |
| `external_irreversible` | 仅在其他 Effect 成功后执行，且必须位于 Bundle 最后一项 |

不可逆 Effect 延迟到最外层 Bundle 的其他 Effect 成功后运行。它的失败仍会使世界事务回滚，
但已经发生的外部结果不能由 KERN 撤销。

外部 adapter 的基础调用接口是：

```python
def invoke(operation: str, payload: dict, context: dict) -> list[dict]: ...
```

需要 receipt 时可以实现：

```python
def invoke_with_receipt(operation: str, payload: dict, context: dict):
    return events, receipt
```

Bridge 支持 `start`、`close`、`checkpoint_restore`、`checkpoint_save`、`bundle_commit` 和
`bundle_rollback` 六个 lifecycle phase。adapter 分别通过 `start`、`close`、
`restore_checkpoint`、`save_checkpoint`、`commit_bundle` 和 `rollback_bundle` 选择性实现这些
回调。最外层 Bundle 共享一个 external transaction ID；child bundle 的 receipt 汇总到该事务。世界失败时，Executor 先恢复
`WorldState`，再发送 rollback；世界 Effect 和延期的不可逆 Effect 成功后发送 commit。

checkpoint archive 与外部 checkpoint 不是一个原子事务。KERN archive 可能已经写入，随后外部
`checkpoint_save` 才失败；调用方必须把这种情况视为失败运行，不能假定两侧已经一致。

runtime config 中的 `external_runtimes` 是实例数组，每项固定为 `runtime_id`、`provider` 和
`options`。`provider` 必须由已选 Package 注册，`options` 进入 `package_identity.v2`。

## 7. 模块所有权

| 模块 | 当前责任 |
| --- | --- |
| `KERN/runtime.py` | runtime 装配、tick 生命周期和记录输出 |
| `KERN/package.py` | Package 选择、数据组合、扩展注册和 catalog 冻结 |
| `KERN/data/` | 数据加载、世界构建、checkpoint 和 archive |
| `KERN/component_catalog/` | ComponentSpec、codec 和转换 catalog |
| `KERN/effects/` | EffectSpec、core definitions 和 effect catalog |
| `KERN/executor/` | Binder、Handler、Bundle 事务和世界回滚 |
| `KERN/interaction/` | Recipe 匹配、ActionIntent 编译和有界 ConversationEngine |
| `KERN/sim/` | Reaction settlement、turn 调度和 turn 执行 |
| `KERN/agent_workflow/` | 决策视图、记忆 patch、Workflow/DialoguePolicy contract、内置 workflow 实现/注册、provider adapter 和 LLM trace |
| `KERN/query/` | condition predicate 和路径解析 |
| `KERN/external_runtime.py` | 外部 adapter 路由与生命周期协议 |
| `KERN/failure_report.py` | 单次 runtime 的失败证据 |
