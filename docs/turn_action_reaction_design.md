# KERN Turn、Action、Event 与 Reaction 设计草案

状态：已按最终合同实施 TurnScheduler 与统一 Event 模型

建立日期：2026-07-25
适用范围：Simulation tick 调度、主动控制实体、Agent workflow、Action/Recipe、Effect/Event、Reaction、interaction 感知与同 tick 重试。

本文整理 2026-07-24 至 2026-07-25 围绕 interaction、感知记忆、ActionRejected、同 tick 重试以及主动行动调度的设计讨论。文中明确区分当前实现和目标模型。本文中的目标模型和参数是本次实施合同；玩家输入、跨进程 pending Turn 等未来能力不属于本次范围。

## 1. 要解决的问题

当前代码把以下四个层级混合在了一起：

- 行为由谁发起：Action 或 Reaction；
- 行为如何匹配数据规则：Recipe；
- 世界如何被修改：Effect 与 EffectBundle；
- 何时轮到哪个 Entity：Tick、Turn 与调度队列。

最明显的混合点是 `AgentControlTick`。它目前作为 AdvanceTick Reaction 的 Effect，在 Effect Handler 内部调用 workflow，再嵌套执行 Agent 产生的多个 Recipe Bundle。由此产生以下问题：

1. 一个 Decision 中的全部 command 会在任何 Action 执行前一次性匹配 Recipe。
2. 后续 command 不会基于前一个 Action 及其 Reaction 结算后的世界重新判断。
3. 后续 command reject 时，前面尚未执行的 command 也不会提交。
4. 多个 Action 的 Reaction 不会自然地插入每个 Action 之间。
5. Agent 主动行动成为 Reaction Bundle 内的嵌套事务。
6. `max_actions_in_tick` 实际更接近“决策批次”计数，而不是成功 Action 计数。

目标是建立清晰的控制层：Tick Scheduler 分配 Turn，Turn 内的 Action 逐个提交，每个 Action 后完整结算 Reaction。

## 2. 设计原则

以下原则已在讨论中达成一致：

1. 所有 WorldState 写入继续通过 Effect 和 WorldExecutor 完成。
2. 一个 EffectBundle 是一个原子世界事务；其中任一 Effect 失败，整个 Bundle 回滚。
3. Event 只在包含它的 Bundle 成功提交后发布。
4. Reaction 只响应已经提交的 Event。
5. 一个 Agent Action 必须基于执行当时的世界单独匹配 Recipe。
6. 每个 Action 完成后必须先把其 Reaction 链结算到稳定状态，再执行下一个 Action。
7. ActionRejected 是合法业务结果；KernFailure 是契约或运行错误。
8. 前面已经提交的 Action 不因后续 ActionRejected 而回滚。
9. Agent 在同一个 Tick 内可以因为 ActionRejected 重新决策；重试撞墙会使模拟失败并中断。
10. Interaction 是否可感知在其发生时确定；Agent 后续移动不改变历史感知结果。

## 3. 领域术语

### 3.1 Tick

一次模拟时间推进。一个 Tick 包含被动世界更新和主动实体行动两个阶段。主动阶段中的多个 Turn 和 Action 不推进模拟时间。

### 3.2 Controller Capability

Entity 是否具备主动控制能力的组件能力。本次实现支持：

- `AgentControlComponent`；
- `LogicControlComponent`。

`PlayerControlComponent` 不进入本次主动候选集合。玩家输入需要 pending Turn、暂停和恢复合同，待该能力设计完成后再接入同一个 Controller seam。

具备 Controller Capability 不会改变 Entity 的世界层级。它只决定 Tick Scheduler 是否把该 Entity 纳入主动行动候选集合。

### 3.3 Turn

Tick Scheduler 授予一个 Entity 的主动行动窗口。Turn 是 Runtime 调度范围，不是世界 Entity，也不需要注册进 WorldState。

同步 LLM 或逻辑 Controller 下，Turn 可以是临时 `TurnContext`。如果 Runtime 支持等待玩家输入、退出进程和稍后恢复，pending Turn 必须持久化到 Runtime scheduler state，但仍不属于世界实体模型。

### 3.4 DecisionRound

Controller 在一个 Turn 中进行的一次调用。一个 DecisionRound 返回一个有序 ActionPlan 或 `end_turn`。

一次 Turn 可以包含多个 DecisionRound：ActionPlan 全部成功且 Agent 仍未进入长期 Task 时进行正常续决策；ActionRejected 时进行 Replan。

因此不采用“一次 Decision 等于一次 Turn”的定义。

### 3.5 ActionIntent

Controller 主动提出的一个动作意图。它包含 `verb`、`target_id` 和 `parameters`，对应当前 command 的领域含义。

ActionIntent 尚未证明可执行，也没有修改世界。

### 3.6 ActionPlan

一个 DecisionRound 返回的有序 ActionIntent 列表。ActionPlan 不是事务，Runtime 必须逐项基于最新 WorldState 解析和提交 Action。

ActionPlan 中任一 ActionRejected 时，尚未执行的 ActionIntent 全部丢弃。任一 Action 成功启动长期 Task 时，Scheduler 立即强制结束 Turn，尚未执行的计划项也不再执行。

### 3.7 ActionAttempt

Runtime 对一个 ActionIntent 进行 Recipe 匹配和执行的完整尝试。ActionAttempt 有三种结果：

- `Committed`：匹配 Recipe，Bundle 成功提交且 Reaction 已结算；
- `Rejected`：意图结构合法，但当前世界不存在可执行路径；
- `EngineFailure`：Binder、Handler、Bundle、Reaction、Provider 或内核未履行契约。

### 3.8 Recipe

把 ActionIntent 与当前 WorldState 匹配为 EffectBundle 的数据规则。

```text
ActionIntent + Current WorldState
-> Recipe matching
-> EffectBundle 或 ActionRejected
```

Recipe 不执行 Bundle，也不直接写 WorldState。

### 3.9 Effect

KERN 轻量数据 DSL 的一条世界写入指令。Effect 经 Binder 校验和规范化后由 Handler 执行。

### 3.10 EffectBundle

按顺序执行的一组 Effect，也是世界事务边界。一个成功 ActionAttempt 通常对应一个顶层 Action Bundle；一个 Reaction 也产生自己的 Reaction Bundle。

### 3.11 Event

Effect 在成功执行且所属 Bundle 提交后发布的事实。Event 是 Reaction 唯一匹配的输入。

### 3.12 Reaction

把一个已提交 Event 匹配为 EffectBundle 的数据规则。

```text
Committed Event + Current WorldState
-> Reaction matching
-> EffectBundle
```

Reaction 可以产生更多 Event，形成 Reaction 链。Reaction 不调用 Controller，不创建嵌套 Action。

### 3.13 Interaction

Agent 可感知的行动或反应记录。Recipe、Reaction 或其他 Bundle 可以通过 `RecordInteraction` 显式产生 Interaction。只有定义了 `narrative_success` 的 Recipe/Reaction 才自动产生成功 Interaction。

## 4. Effect 与 Event 的统一模型

### 4.1 单一事件概念

目标模型取消 Reaction DSL 中 `on_effect` 和 `on_event` 两套匹配机制，只保留 `on_event` 按 Event 类型匹配，例如：

```json
{
  "on_event": "AddTag",
  "condition": {},
  "bundle": {"effects": []}
}
```

Event 必须保留 `source_effect`、规范化输入、Bundle ID、Action ID 等审计字段，但这些字段不构成第二种触发机制。

### 4.2 默认 Event

Executor 会为每个成功 Effect 生成一个默认 Event，Event 类型就是 Effect ID。Handler 没有提供手写 Event 时，该默认 Event 是这个 Effect 唯一的 Event：

```json
{
  "type": "AddTag",
  "source_effect": "AddTag",
  "input": {
    "target": "self",
    "tag": "hungry"
  }
}
```

大部分 Effect 应使用默认 Event。只有需要公布实际运行结果、生成 ID 或更明确领域事实的 Effect 才手写 Event，例如 `EntityDestroyed`、`TaskCreated`。

目标约定：

- Handler 返回零个 Event：生成一个默认 Event；
- Handler 返回一个或多个 Event：先发布这些手写 Event，再追加一个默认 Event；
- Binder 或 Handler 失败：不发布 Event，抛出 KernFailure；
- Handler 成功但同 Bundle 后续 Effect 失败：整个 Bundle 回滚，不发布任何 Event。

默认 Event 始终存在。它表示该 Effect 已成功完成；手写 Event 用于公布更具体的运行事实。

### 4.3 Event Envelope

Event envelope 统一保留：

```text
type
source_effect
input
context
facts / payload
bundle_id
parent_bundle_id
action_id
effect_index
```

其中 `type`、`source_effect`、`input`、`context`、`bundle_id`、`parent_bundle_id`、`action_id` 和 `effect_index` 是固定 envelope 字段；Handler 返回的领域字段放入 `payload`。默认 Event 的 `payload` 为空。Reaction 条件通过 `event.payload` 读取领域事实，不再读取旧 `facts` 或 `effect` 别名。

`source_effect` 用于调试和归因。Reaction 只匹配 `type`。

### 4.4 多 Event 的稳定顺序

一个 Effect 可以返回多个手写 Event。Handler 决定手写 Event 的数量、内容及列表顺序；Executor 验证列表并在最后追加默认 Event。

一个 Bundle 的稳定发布顺序为：

```text
Effect 1 custom event 1
-> Effect 1 custom event 2
-> Effect 1 default event
-> Effect 2 custom event 1
-> Effect 2 default event
```

Bundle 成功提交后，WorldSettlement 按这个顺序把 Event 放入 FIFO。Reaction 产生的新 Event 继续追加到 FIFO 尾部。任何一次相同输入和相同 WorldState 的执行都必须得到相同的 Event 顺序。

## 5. Tick Scheduler

### 5.1 两阶段 Tick

目标 Tick 分为两个阶段：

```text
被动阶段
1. game_time.tick + 1
2. 发布 WorldTickAdvanced
3. 按 Entity ID 升序把所有 AdvanceTick 放入同一个 Event FIFO
4. 按 FIFO 完整结算被动 Reaction

主动阶段
5. 找出所有具备启用 Controller Capability 的 Entity
6. 建立稳定的 Turn 候选顺序
7. 逐个执行 Entity Turn
8. 全部 Turn 结束后完成当前 Tick
```

`WorldTickAdvanced` 单独发布并结算。随后 Runtime 建立按 Entity ID 升序排列的 Entity 快照，把全部 `AdvanceTick` 一次性交给 WorldSettlement；Settlement 按 FIFO 处理 Event 及其 Reaction。主动阶段只在这两个 FIFO 都清空后开始。这避免较早遍历的 Agent 已经行动，而较晚 Entity 尚未接收 AdvanceTick 的顺序偏差。

### 5.2 主动 Entity 候选规则

主动阶段开始时生成一次候选快照：

- 排序模块按 Entity ID 字符串升序排列；
- 轮到时重新检查 Entity 是否存在、Controller 是否启用、当前是否可行动；
- Tick 中途死亡或失去能力的候选被跳过；
- Tick 中途新创建或新获得 Controller 的 Entity 从下一个 Tick 开始行动；
- 前一个 Agent 的 Action/Reaction 可以影响后续 Agent 的资格。

未来需要 initiative、速度或随机顺序时，只替换排序模块，不改变 TurnScheduler 的其余接口。本次不为尚不存在的排序策略增加抽象注册表或配置分支。

### 5.3 Turn 不是 WorldState 一级对象

Turn 不需要：

- Entity ID 或模板；
- Component；
- 世界位置；
- Recipe target 能力；
- 进入普通世界查询。

TurnContext 至少保存：

```text
turn_id
tick
actor_id
actions_committed
replans
```

短期内不实现玩家控制及跨异步输入等待，因此 TurnContext 只作为同步 Runtime 临时状态存在，不进入 checkpoint。未来加入玩家控制时，再单独设计 pending Turn 的暂停、超时和恢复契约。

## 6. Turn 与 Action 执行

### 6.1 Controller 输出

一个 DecisionRound 返回一个非空、有序 ActionPlan 或结束 Turn。最终 wire shape 为：

```json
{
  "type": "action_plan",
  "actions": [
    {
      "verb": "YieldCurrentTask",
      "parameters": {}
    },
    {
      "verb": "Consume",
      "target_id": "food_01",
      "parameters": {}
    }
  ]
}
```

```json
{"type": "end_turn"}
```

空 ActionPlan 不具有明确语义，应视为 workflow contract failure；Controller 使用显式 `end_turn` 结束 Turn。

Runtime 接受整个 ActionPlan，但每次只授权并执行其中一个 Action。计划内每个 Action 后都要完整结算 Reaction，再基于最新世界处理下一项。

### 6.2 Turn 循环

```text
开始 Turn
-> 检查 Entity 当前是否可行动
-> 构造感知与记忆
-> Controller 返回 ActionPlan 或 end_turn
-> end_turn: 结束 Turn
-> ActionPlan: 从第一项开始逐个执行 ActionAttempt
-> 每个 Action 后完整结算 Reaction 并重新检查 Entity
-> ActionRejected: 丢弃剩余计划，反馈原因并 Replan
-> 进入长期 Task: 丢弃剩余计划并强制结束 Turn
-> 整个计划成功且没有长期 Task: 进入下一轮正常 DecisionRound
```

未来的玩家 Controller 可以暂停 Runtime 等待输入；LLM 和逻辑 Controller 可以同步返回。

短期目标不实现玩家 Controller，因此首个 TurnScheduler 只需要支持同步 LLM 和逻辑 Controller。

### 6.3 Turn 开始、继续与结束的权责

原先模糊的 `should_take_turn` 拆成三个判断：

1. Scheduler 判断 `is_turn_eligible`：Entity 是否存在、是否具备启用的 Controller、是否受到死亡或其他硬性状态限制；
2. DecisionArbiter 返回 `TurnAssessment`：当前是否值得询问 Controller，以及原因和模式；
3. 已经获得 Turn 后，Controller 通过 ActionPlan 或 `end_turn` 表达主动意图，TurnRunner 负责逐项执行计划，Scheduler 保留预算、长期 Task 和硬约束下的强制结束权。

DecisionArbiter 输出为：

```text
TurnAssessment
  decision = skip | request
  mode = normal | task_interrupt
  reason
  priority
```

DecisionArbiter 只负责决定是否请求一次 Controller 注意。它不调用 LLM、不执行 Action，也不结束已经开始的 Turn。

正在执行 Task 的 Entity 如果没有任何中断条件，DecisionArbiter 返回 `skip`，Scheduler 不调用 Controller。如果低营养、感知变化等规则触发，DecisionArbiter 返回 `request/task_interrupt`，Scheduler 才授予 Turn。

Turn 已经开始后：

- Controller 返回 `end_turn`：自愿结束 Turn；在 `task_interrupt` 模式下表示已经看到中断但决定继续当前 Task；
- Controller 返回 ActionPlan：TurnRunner 逐项执行，每项后结算 Reaction 和检查硬约束；
- ActionPlan 全部成功且没有长期 Task：再次调用 Controller，这是正常续决策，不计入 Replan；
- Action 启动长期 Task：Scheduler 立即强制结束 Turn并丢弃剩余计划；
- Scheduler 在 Entity 失去资格、达到预算、Runtime terminal 或其他强制条件下结束 Turn。

### 6.4 Action Committed

```text
ActionIntent
-> 用当前 WorldState 匹配 Recipe
-> 获得一个 Action Bundle
-> 作为顶层 Bundle 执行
-> Bundle 提交
-> Event 进入 Reaction FIFO
-> Reaction 链结算到队列为空
-> actions_committed + 1
-> 如果计划仍有下一项，使用最新 WorldState 继续处理
```

ActionPlan 不是事务。每个 Action Bundle 都是独立顶层事务，不嵌套在 Reaction Bundle 中。前一个 Action 及其 Reaction 结算完成后，下一项才进行 Recipe 匹配。

### 6.5 ActionRejected 与同 Tick 重试

ActionRejected 是 ActionAttempt 的合法结果，不是错误。典型原因包括：

- target 不存在；
- 没有匹配 Recipe；
- Recipe condition 在当前世界不成立；
- 前一个 Action 或其 Reaction 改变了后续可执行条件。

目标流程：

```text
Recipe resolution rejected
-> 生成 rejection RecordInteraction Bundle
-> 作为独立顶层 Bundle 提交
-> Agent 在发生时获得 rejection interaction inbox
-> 清除 ActionPlan 中尚未执行的全部 ActionIntent
-> replans + 1
-> 同一个 Tick、同一个 Turn 开始新的 DecisionRound
```

Rejection Interaction 包含：

```json
{
  "status": "rejected",
  "reason": "TARGET_MISSING",
  "interaction_origin": "action_rejection",
  "extra": {
    "narrative": "目标已经不存在",
    "rejection_code": "TARGET_MISSING",
    "message": "Target entity not found",
    "action_id": "action_42"
  }
}
```

因为 interaction 感知已经改为发生时写入 `PerceptionComponent.interaction_inbox`，下一次 DecisionRound 会在 memory policy 处理后同时获得正式记忆和一次性的 `recent_interactions`。

Replan 时还应直接提供结构化 rejection context，至少包含 `action_id`、拒绝 code/message 和被拒绝的 ActionIntent。这样 Controller 不需要只从 narrative 中推断失败原因。

### 6.6 预算与失败

使用两个独立的全局 Runtime 配置：

- `max_actions_per_turn`：成功提交的 Action 数量上限，默认 `99`；达到后正常结束 Turn；
- `max_replans_per_turn`：ActionRejected 引起的重新决策上限，默认 `5`；超过后抛出 KernFailure 并终止模拟。

ActionPlan 全部成功后再次调用 Controller 属于正常续决策，不增加 `replans`。成功 Action 会持续增加 `actions_committed`，因此整个 Turn 仍受到 `max_actions_per_turn` 的确定性限制。

Action Bundle、Reaction Bundle 或 rejection RecordInteraction Bundle 自身出现 KernFailure 时，不重试，不转成 rejection，直接终止模拟。

### 6.7 Action 记录

不新增独立 Action log。ActionRunner 为每次 ActionAttempt 分配确定性 `action_id`，格式为 `tick:{tick}:turn:{turn_index}:attempt:{attempt_index}`。`turn_index` 是当前 Tick 稳定候选快照中的零基序号，`attempt_index` 在一个 Turn 中从零递增并同时覆盖 committed 和 rejected attempt。Event 与 interaction log 通过 `action_id` 关联。调试或归档时从这两类现有日志重建 Action 的意图、提交结果和可感知叙事。

Action 启动长期 Task 的判定是：Action 执行前 actor 没有 `current_task_id`，Reaction 完整结算后 actor 出现非空 `current_task_id`。只有这个状态跃迁触发强制结束 Turn。

## 7. Reaction Settlement

每个顶层 Bundle 提交后，WorldSettlement 使用 FIFO 处理其 Event：

```text
Committed Bundle
-> Event FIFO
-> 匹配 Reaction
-> 执行一个 Reaction Bundle
-> 发布新的 Event
-> 追加到 FIFO
-> 直到 FIFO 为空
```

逻辑上的 Reaction 链可以有深度限制，但不应通过 Agent Action 嵌套表示。Scheduler 只有在 Reaction FIFO 为空后才能执行下一个 Action。

Reaction 可以改变世界、写 Interaction、创建任务或产生其他 Event。Reaction 不调用 Controller，也不授予 Turn。

## 8. 一个完整 Tick 的运行示例

假设 Tick 42 开始时有四个受控 Entity，初始排序模块按 ID 得到：

```text
camper_caregiver
camper_explorer
camper_organizer
camper_repairer
```

其中：

- `camper_explorer` 正在执行探索 Task，当前没有中断；
- `camper_organizer` 正在执行整理营地 Task，但营养已经降到中断阈值以下；
- 另外两人没有进行中的 Task。

### 8.1 被动阶段

```text
game_time: 41 -> 42
-> 发布 WorldTickAdvanced
-> 依次给全部 Entity 发布 AdvanceTick
-> Worker/Status/Environment 等 Reaction 执行
-> 所有被动 Reaction FIFO 清空
```

探索和整理 Task 都在这一阶段获得一次进度。此时仍没有调用任何 LLM。

### 8.2 caregiver 的 Turn

```text
Scheduler: is_turn_eligible = true
DecisionArbiter: 没有 Task，返回 request/normal
Scheduler: 授予 Turn
```

Runtime 处理 caregiver 的 interaction inbox、构造当前感知并调用 Controller。Controller 返回一个只有一项的 ActionPlan：

```json
{
  "type": "action_plan",
  "actions": [
    {
      "verb": "Inspect",
      "target_id": "camp_storage",
      "parameters": {}
    }
  ]
}
```

ActionRunner 用 Tick 42 的当前世界匹配 Recipe，执行一个顶层 Bundle。Bundle 成功后发布手写 Event，并为每个 Effect 追加默认 Event。WorldSettlement 把由这些 Event 触发的 Reaction 全部结算。

结算完成后 caregiver 仍具备行动资格，Scheduler 再次调用 Controller。Controller 返回：

```json
{"type": "end_turn"}
```

caregiver 的 Turn 结束，行动权交给 explorer。

### 8.3 explorer 没有获得 Turn

```text
Scheduler: is_turn_eligible = true
DecisionArbiter: 当前 Task 正常执行，没有低营养或感知变化
DecisionArbiter: 返回 skip
```

Scheduler 不调用 explorer 的 Controller，探索 Task 保持执行，直接处理 organizer。

### 8.4 organizer 的 Task 中断 Turn

```text
Scheduler: is_turn_eligible = true
DecisionArbiter: LowNutrition 触发
DecisionArbiter: 返回 request/task_interrupt
Scheduler: 授予 Turn，reason=low_nutrition
```

Runtime 把当前 Task、低营养原因、最新 interaction 和记忆提供给 Controller。

第一轮 DecisionRound 返回一个包含三个 Action 的 ActionPlan：

```json
{
  "type": "action_plan",
  "actions": [
    {
      "verb": "YieldCurrentTask",
      "parameters": {}
    },
    {
      "verb": "Consume",
      "target_id": "initial_canned_food_01",
      "parameters": {}
    },
    {
      "verb": "AcceptTask",
      "target_id": "camp_storage",
      "parameters": {}
    }
  ]
}
```

TurnRunner 不会预先编译三项，而是逐项处理：

```text
YieldCurrentTask Bundle committed
-> Reaction FIFO 清空
-> 整理 Task 已停止，继续处理计划下一项

Consume 使用最新 WorldState 匹配 Recipe
-> Consume Bundle committed
-> nutrition 等状态被修改
-> 手写 Event 按 Handler 顺序发布
-> 每个 Effect 的默认 Event 随后发布
-> RecordInteraction 在发生时写入同地点 Agent inbox
-> 所有 Reaction 结算完成
-> actions_committed = 2

AcceptTask 使用 Consume 和 Reaction 之后的 WorldState 匹配 Recipe
-> AcceptTask Bundle committed
-> organizer 进入长期 Task
-> Scheduler 立即强制结束 Turn
```

如果 ActionPlan 只有 Yield 和 Consume 两项，并且两项都成功、没有建立长期 Task，那么计划耗尽后 Runtime 会在同一个 Turn 中再次调用 Controller。下一轮 DecisionRound 可以返回新的 ActionPlan 或 `end_turn`，这属于正常续决策，不增加 `replans`。

如果 `initial_canned_food_01` 在当前世界已经不存在，Recipe resolution 返回 ActionRejected：

```text
Consume ActionAttempt rejected
-> 提交 rejection RecordInteraction Bundle
-> organizer 立即获得 TARGET_MISSING interaction
-> 丢弃尚未执行的 AcceptTask
-> replans = 1
-> 同一个 Tick、同一个 Turn 重新构造感知
-> Controller 收到结构化 rejection context
-> Controller 可以返回新的 ActionPlan 或 end_turn
```

这个 rejection 不回滚 organizer 已经提交的 `YieldCurrentTask` Action。只有 replans 超过全局配置 `5`，或 rejection 记录自身发生 KernFailure，模拟才会中断。

### 8.5 repairer 与 Tick 结束

organizer Turn 结束后，Scheduler 使用同样流程处理 repairer。repairer 结束 Turn 后，主动候选队列为空，Tick 42 完成。下次 `Runtime.step()` 才会把时间推进到 Tick 43。

## 9. Interaction 感知与记忆

这部分设计已经在当前工作树中实现。

### 9.1 发生时感知

`RecordInteraction` 执行时：

1. 写入包含 `tick`、`time_str` 和 `interaction_id` 的 interaction log；
2. 根据当时 WorldState 选择参与者和同地点、启用 PerceptionComponent 的 Entity；
3. 把深拷贝 interaction 快照写入其 `PerceptionComponent.interaction_inbox`；
4. interaction log 与所有 inbox 写入属于同一个 Bundle 事务。

Agent 后续离开地点仍保留当时感知；后来进入地点的 Agent 不会追溯获得旧 interaction。

### 9.2 决策时加工

Agent 决策前：

1. Runtime 读取该 Agent 的 interaction inbox；
2. 共享 memory policy 对 interaction 打分并生成正式记忆；
3. `ApplyMemoryPatch` 原子地写入记忆并消费 inbox；
4. 同一批 interaction 作为一次性的 `recent_interactions` 提供给本轮决策；
5. 正式记忆和 recent interaction 都保留发生时的 `tick` 与 `time_str`。

该设计已经消除了全局 interaction log 扫描和 `last_interaction_seq_seen` cursor。

## 10. Effect、Recipe 与 Reaction 的必要性

KERN 已经形成一个轻量数据 DSL：

- Effect 是 DSL 指令集；
- EffectBundle 是事务和组合结构；
- Recipe 是 ActionIntent 到 EffectBundle 的规则编译器；
- Reaction 是 Event 到 EffectBundle 的规则编译器；
- WorldExecutor 是绑定、验证和执行该 DSL 的内核模块。

数据驱动不意味着没有 DSL。场景作者需要一套稳定、可验证、可回滚的数据语言表达行为。当前需要重构的是 Turn/Action 调度层，而不是删除 Recipe、Effect 或 Bundle。

## 11. 当前实现与目标模型的差异

| 区域 | 当前实现 | 目标模型 |
|---|---|---|
| Agent 调度 | AdvanceTick Reaction 产生 `AgentControlTick` Effect | Tick Scheduler 直接发现主动 Entity 并分配 Turn |
| Turn | 未显式建模 | Runtime 中的 TurnContext |
| workflow 输出 | `apply_commands` 列表或 `noop` | `action_plan.actions` 或显式 `end_turn` |
| command 执行 | 先批量匹配全部 Recipe，再连续执行 | ActionPlan 非事务；每个 Action 基于最新世界单独匹配、提交并结算 Reaction |
| Action/Reaction 顺序 | Agent Action 嵌套在 Reaction Effect Handler 中 | Action 顶层提交，Reaction 结算后才允许下一个 Action |
| rejection | 返回 `ActionRejected` 后结束当前循环 | 独立记录 rejection interaction，同 Turn 重新决策 |
| Action 预算 | `max_actions_in_tick` 按批次近似计数 | 成功 Action 与 replan 分开计数 |
| 默认 Event | `EffectExecuted` | Event type 默认等于 Effect ID |
| Reaction 匹配 | `on_event` 与 `on_effect` | 单一 Event type 匹配 |
| interaction 感知 | 已迁移到发生时 inbox | 保持当前实现 |

## 12. 一次性实施顺序

以下阶段只表示代码依赖顺序，不是可以发布、提交或长期保留的架构状态。本次改造只有一个完成状态，并遵守以下限制：

- 不增加 feature flag、fallback、legacy adapter 或双 Scheduler；
- 不同时接受新旧 workflow decision type；
- 不同时接受 `on_event` 与 `on_effect`；
- 新路径接通后立即删除 `AgentControlTick`、批量 command 预编译和嵌套 Action 执行；
- 只有最终合同的全量验收通过后，改造才算完成。

### 阶段 1：统一 Event 模型

1. 明确 Handler Event 返回契约；
2. 默认 Event type 改为 Effect ID；
3. 保留 `source_effect` 作为审计字段；
4. 将 Reaction schema 收敛为单一 `on_event` 匹配；
5. 删除 `on_effect`，迁移或删除旧测试。

### 阶段 2：引入 TurnScheduler

1. Runtime Tick 分成被动和主动阶段；
2. 主动阶段查询所有启用 Controller Capability 的 Entity；
3. 建立稳定 Turn 候选顺序；
4. 引入临时 TurnContext，不写入 WorldState。

### 阶段 3：引入 ActionPlan Contract

1. workflow contract 表达非空有序 ActionPlan 或显式 `end_turn`；
2. workflow provider、validator 和调用方统一改为 `action_plan.actions`，删除 `apply_commands` 和 `noop`；
3. Recipe 每次只解析当前一个 ActionIntent；
4. 一个 Action Bundle 作为顶层事务执行；
5. 每个 Action 后等待 Reaction FIFO 清空，再处理计划下一项；
6. 计划耗尽且 Agent 未进入长期 Task 时再次调用 Controller。

### 阶段 4：接通 rejection replan

1. Recipe rejection 生成独立 RecordInteraction Bundle；
2. rejection 提交后重新构造 Agent 感知和记忆；
3. 同一个 Turn 开始新的 DecisionRound；
4. 加入独立 action/replan 预算；
5. 超过 replan 上限时抛出带完整上下文的 KernFailure。

### 阶段 5：删除旧控制路径

1. 删除 `AgentControlTick` Effect 及其 Camping Reaction；
2. 删除 `_commands_to_operations` 的批量预编译行为，改为逐个 ActionIntent 解析；
3. 删除 `run_agent_control_tick` 的嵌套 Bundle 路径；
4. 更新 Runtime、Package 和开发者文档；
5. 保留少量跨模块契约验证，删除依赖旧嵌套行为的测试。

## 13. 最终验收

1. `WorldTickAdvanced` 完整结算后，全部 `AdvanceTick` 按 Entity ID 升序进入同一个 FIFO；全部被动 Reaction 完成后才出现第一个 Turn。
2. 主动候选只包含启用的 `AgentControlComponent` 或 `LogicControlComponent`，候选按 Entity ID 升序快照，并在轮到时重新检查资格。
3. workflow 只接受非空 `action_plan.actions` 或 `end_turn`；仓库中不存在运行时 `noop`、`apply_commands` 兼容分支。
4. ActionPlan 逐项即时匹配。每个 Action Bundle 顶层提交并完整结算 Reaction 后，下一项才能匹配。
5. Rejection 丢弃剩余 Action，保留之前提交的 Action，在同 Tick、同 Turn 使用结构化 rejection context replan；超过预算产生 KernFailure。
6. Action 新启动长期 Task 后强制结束 Turn；已有 Task 未发生状态跃迁时不误判为新 Task。
7. 每个成功 Effect 的 custom Event 按 Handler 顺序发布，最后追加默认 Effect-ID Event；Bundle 回滚不发布任何 Event。
8. Reaction 只使用 `on_event` 匹配 `event.type`；仓库中不存在 `on_effect` 数据或运行时分支。
9. `AgentControlTick` Effect、Camping Reaction、`run_agent_control_tick` 和批量 `_commands_to_operations` 路径全部删除。
10. 聚焦契约测试、全量 unittest、compileall、scenario lint 和 Camping smoke 全部通过。
