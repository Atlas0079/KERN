# Failure 与 Event 契约

状态：已实施

## 术语

### ActionRejected

Decision 产生的意图符合 Decision schema，但当前世界没有可执行路径。

示例：

- 不存在匹配 Recipe；
- 目标实体不存在；
- Recipe condition 不满足。

ActionRejected 是正常 Action 结果。它不写错误 Event，不终止 Runtime，也不进入 Reaction FIFO。

### KernFailure

KERN、Package、Provider 或运行环境未能履行契约。KernFailure 会终止当前模拟。

Failure 的稳定字段为：

```text
code
message
origin
phase
context
cause / traceback
```

Executor、Binder、Workflow、Reaction、Persistence 和 External runtime 的 Failure 都通过 Python exception 传播。Bundle 在异常路径恢复快照，Runtime 在公开执行入口捕获第一次 Failure。

### Event

Effect 成功执行后产生的机器可读 Event。Event 只在包含它的 Bundle 成功提交后写入 `event_log` 并交给 Reaction。

记录包含：

```text
type
source_effect
input                 Binder 规范化后的 Effect 输入
context               执行上下文（去除递归 event 副本）
payload               Handler 提供的领域事实
bundle_id
parent_bundle_id
action_id
effect_index
```

动态 `param:*` 值在 Binder 阶段解析后进入 `input`。Handler 返回的 Event 按原顺序发布，领域事实进入 `payload`；随后 Executor 追加一个 `type=Effect ID` 的默认 Event。

## 运行链

```text
Decision
-> ActionRejected
   或
-> ActionIntent -> Recipe Bundle -> Binder -> Handler
   -> KernFailure: 回滚、写 failure.json、终止
   或
   -> Bundle committed -> custom Event -> default Event -> Reaction matching
```

Reaction 依次执行：

1. `on_event` 匹配 Event 的 `type`；
2. `selector` 条件；
3. `condition` 条件；
4. 生成并执行 Reaction Bundle。

Reaction 只接收已提交记录。Reaction Bundle 的 Failure 直接终止 Runtime。

Recipe 和 Reaction 只有在定义 `narrative_success` 时，才由编译器自动生成一条
interaction 记录；没有 narrative 时不自动产生 interaction。作者仍可在 Recipe、
Reaction 或其他 Bundle 中显式放置任意数量的 `RecordInteraction`；它本身是通用的
Agent 可感知广播 Effect，是否产生重复交互由 Bundle 作者负责。交互文本和额外
可感知数据必须在 `RecordInteraction` 写入时一次性提供；核心不提供事后修改
interaction 的 Effect。Handler 会根据交互发生时的世界状态确定感知者，并把包含
`tick`、`time_str` 和 `interaction_id` 的快照写入其 `PerceptionComponent.interaction_inbox`。
该写入与 interaction log 属于同一个 Bundle 事务。

## Failure 报告

每次 Runtime 最多写一份：

```text
<checkpoint_dir>/failure.json
```

报告保留完整开发者证据，包括原始异常链、traceback、规范化 Effect 输入、Decision、LLM 上下文和执行身份。报告写入失败不会覆盖原始 Failure。
