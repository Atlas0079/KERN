# 外部 Runtime 契约

外部 runtime 表示 `WorldState` 之外的状态和操作，例如数据库事务、设备调用或平台消息。
KERN 通过显式 domain Effect 和 `ExternalRuntimeBridge` 接入这些系统。

## 一致性边界

EffectBundle 的 `WorldState` 写入可以回滚；外部写入不在该快照中。外部 adapter 必须拥有
自己的事务或补偿语义，KERN 只负责调用确定的生命周期 phase、传递 receipt，并在失败时
终止 runtime。

`EffectSpec.side_effect` 只允许：

| 值 | 语义 |
| --- | --- |
| `world` | 只写 `WorldState` |
| `external_transactional` | adapter 拥有真正的回滚能力 |
| `external_compensatable` | adapter 使用 receipt 执行补偿 |
| `external_irreversible` | 仅在其他 Effect 成功后执行，且必须位于 Bundle 最后一项 |

不可逆 Effect 延迟到最外层 Bundle 的其他 Effect 成功后运行。它的失败仍会使世界事务回滚，
但已经发生的外部结果不能由 KERN 撤销，因此 adapter 和 Bundle 作者必须控制操作粒度。

## Adapter 操作

基础 adapter 实现：

```python
def invoke(operation: str, payload: dict, context: dict) -> list[dict]: ...
```

需要 receipt 时可以实现：

```python
def invoke_with_receipt(operation: str, payload: dict, context: dict):
    return events, receipt
```

Event 返回值必须是对象列表，且每项具有非空 `type`。receipt 是 KERN 不解释的对象，只会
按 runtime ID 和 transaction ID 返回给同一生命周期边界。

## 生命周期

Bridge 支持四个 phase：

- `checkpoint_restore`
- `checkpoint_save`
- `bundle_commit`
- `bundle_rollback`

adapter 分别通过 `restore_checkpoint`、`save_checkpoint`、`commit_bundle` 和
`rollback_bundle` 选择性实现这些回调。Bridge 按 runtime ID 排序调用 adapter。

最外层 Bundle 共享一个 external transaction ID；child bundle 的 receipt 汇总到该事务。
世界失败时，Executor 先恢复 `WorldState`，再发送 rollback；世界 Effect 和延期的不可逆
Effect 成功后发送 commit。生命周期失败抛出 `ExternalRuntimeLifecycleError`，携带 phase、
runtime ID、transaction ID 和可用 receipt，并使公开 runtime 入口进入 terminal 状态。

checkpoint archive 与外部 checkpoint 不是一个原子事务。KERN archive 可能已经写入，随后
外部 `checkpoint_save` 才失败；调用方必须把这种情况视为失败运行，不能假定两侧已经一致。

## Package 与配置

Package 只声明 domain Effect、Component、codec 和数据。provider、checkpoint 参数和具体
adapter 实例属于 runtime 装配。选择 Package 表示信任其 Effect 代码，但不会自动创建外部
连接或注入 adapter。

