# Failure 与 EffectRecord 契约

状态：已开始实施

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

### EffectRecord

Effect 成功执行后产生的机器可读记录。记录只在包含它的 Bundle 成功提交后写入 `event_log` 并交给 Reaction。

记录包含：

```text
record_type = EffectRecord
effect
input                 Binder 规范化后的 Effect 输入
_effect_context       执行上下文（去除递归 event 副本）
facts                 Handler 可选提供的事实
bundle_id
parent_bundle_id
action_id
effect_index
```

动态 `param:*` 值在 Binder 阶段解析后进入 `input`。Handler 的事实保留在 `facts` 和兼容的顶层字段中，供需要生成 ID 或实际结果的 Reaction 使用。

## 运行链

```text
Decision
-> ActionRejected
   或
-> Command -> Recipe Bundle -> Binder -> Handler
   -> KernFailure: 回滚、写 failure.json、终止
   或
   -> Bundle committed -> EffectRecord -> Reaction matching
```

Reaction 依次执行：

1. `on_event` 匹配记录的 `type`；
2. `on_effect` 匹配记录的 `effect`；
3. `selector` 条件；
4. `condition` 条件；
5. 生成并执行 Reaction Bundle。

Reaction 只接收已提交记录。Reaction Bundle 的 Failure 直接终止 Runtime。

Recipe 产生的成功 interaction 通过 `RecordInteraction` Effect 写入；需要把
细节附加到最近一次 interaction 时使用 `UpdateInteractionDetails` Effect。
这两个 Effect 与同一 Bundle 一起提交或一起回滚。

## Failure 报告

每次 Runtime 最多写一份：

```text
<checkpoint_dir>/failure.json
```

报告保留完整开发者证据，包括原始异常链、traceback、规范化 Effect 输入、Decision、LLM 上下文和执行身份。报告写入失败不会覆盖原始 Failure。
