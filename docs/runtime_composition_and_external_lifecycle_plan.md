# 运行时组合与外部生命周期修改计划

状态：阶段 0–3 已实施（2026-07-19）；阶段 4 按本文件约定另行规划。本文件记录 2026-07-19 架构审查中已达成的决策，以及据此确定的实施方案。

## 实际目标

保持 Package 组合可复现、无歧义；当外部 runtime 操作失败时，使失败可见并终止运行，避免仿真世界与外部系统在未被察觉的情况下进入不一致状态。

本计划覆盖运行时装配、effect bundle 执行和外部 runtime 生命周期回调。它不会为场景包增加参数，不会改变场景行为，也不会假定所有外部系统都可以提供真正的事务能力。

## 已确认的决策

### 场景包保持声明式

- Package 只声明它提供的数据、组件、codec 与 effect。
- Package 不携带运行时参数。
- provider 选择、tick 上限、checkpoint 设置、外部 runtime 设置等参数，只能来自 runtime config。
- runtime config 同时负责选择一次运行所使用的 Package 组合。

### 外部回滚属于生命周期职责

- 外部 runtime 操作可能无法回滚。
- 因此，外部回滚不能作为普通的、尽力而为的世界 effect 表达。
- 回滚回调与现有外部 checkpoint 保存/恢复回调处于同一架构层级。
- 外部生命周期回调失败时，必须采用一致、明确的 runtime 级处理方式。

### 复用现有外部 checkpoint 恢复能力

- 现有 `SQLiteSocialPlatformRuntime.restore_checkpoint(...)` 已保存并恢复社交平台全部数据表的快照；它不是只有通知的空实现。
- 本计划保留该恢复模型，不重新设计外部 runtime 的 checkpoint 数据格式或恢复算法。
- 本计划只将 checkpoint 保存/恢复接入统一的外部生命周期错误与终止语义。

## 已确认的实施方案

### 显式区分包选择与运行参数

将 config 解析为两个不可变值：

```text
RuntimeConfig
├─ PackageSelection  （Package 路径和被选择的世界包）
└─ RuntimeOptions    （全部运行时参数）
```

`LoadedPackages` 继续表示 `PackageSelection` 的解析结果：世界数据、冻结后的 catalog 和组合身份。它不保存运行时参数。

`KernRuntime.from_config(...)` 从同一份 config 解析这两个值。更底层的装配 API 可以接收 `LoadedPackages` 与 `RuntimeOptions`。如果公开 API 仍同时接收 `LoadedPackages` 和 config 路径，它必须验证 config 的 `PackageSelection` 与传入的组合身份一致，不能静默忽略 config 中的 `packages` 字段。

### 将外部回调统一为生命周期 phase

保留 checkpoint 回调，并增加 bundle 级 phase：

```text
checkpoint_save
checkpoint_restore
bundle_commit
bundle_rollback
```

bridge 按确定的 runtime ID 顺序调用 adapter。任何失败都表示为一种带类型的生命周期错误，至少携带 phase、runtime ID、transaction ID 和可用的操作 receipt。

建议的失败策略：

- checkpoint 保存/恢复失败：保留当前的快速失败行为；停止装配或推进，并暴露生命周期错误；
- bundle 回滚失败：先恢复 `WorldState`，再终止 runtime；外部状态的不确定性应作为诊断信息，不应成为继续 tick 的理由；
- 世界提交后的 bundle commit 失败：终止 runtime，并记录“世界已提交、外部结果不确定”的状态。

发生生命周期失败后，runtime 进入终止且不可推进的状态。可保留内存状态用于诊断，但 `run`、`step` 和 `advance_ticks` 必须拒绝继续执行。

### 声明外部操作的回滚能力

将当前未被使用的自由字符串 `EffectSpec.side_effect` 收敛为受校验的策略，例如：

```text
world
external_transactional
external_compensatable
external_irreversible
```

当 runtime 需要回滚或补偿某项外部操作时，adapter 返回对应 receipt。executor 为整个 bundle transaction 保存这些 receipt；嵌套 child bundle 属于同一个 transaction。

语义如下：

- `external_transactional`：adapter 自己拥有回滚能力，例如尚未提交的 SQLite transaction；
- `external_compensatable`：发生 `bundle_rollback` 时，bridge 使用 receipt 调用 adapter 的补偿操作；
- `external_irreversible`：将操作排入 `bundle_commit`，仅在世界 transaction 成功后执行；不得假装它可以回滚。

## 实施阶段

### 阶段 0：明确契约并保护现有行为（已完成）

- 添加聚焦测试，展示当前 `LoadedPackages` 与 config 可不匹配的风险。
- 添加生命周期回调顺序、adapter 失败传播以及终止失败后拒绝推进的测试。
- 记录现有 checkpoint 的非原子性：KERN archive 可以先写入成功，随后外部 checkpoint 回调失败。

验收：现有 package loading、executor transaction、world settlement、archive 和 external runtime 测试继续通过。

### 阶段 1：消除运行时装配输入的歧义（已完成）

- 引入内部 `PackageSelection` 与 `RuntimeOptions` 值。
- 重构 `KernRuntime.from_config(...)`，使其只解析一次 config。
- 将私有的 `_loaded_packages or load_packages_from_config(...)` 分支替换为显式的底层装配路径。
- 当传入的 `LoadedPackages` 与 config 选择的 Package 组合身份不同，立即拒绝。

验收：用相同包选择复用组合可以工作；将组合与不同 config 的包选择混用时，在构建世界前失败。

### 阶段 2：建立外部生命周期协议（已完成）

- 扩展 `ExternalRuntimeAdapter` 与 `ExternalRuntimeBridge`，提供带类型、顺序确定的生命周期调用和专用错误类型。
- 将当前 checkpoint 保存/恢复接入统一机制，保持其快速失败策略不变。
- 定义 adapter 如何报告操作 receipt 与能力分类。

验收：adapter 调用顺序确定；回调失败报告 phase 与 runtime ID；checkpoint 行为由聚焦测试覆盖。

### 阶段 3：将生命周期接入 bundle 执行（已完成）

- 引入由嵌套 child bundle 共享的 bundle transaction ID。
- executor 与 lint 依据 catalog 中的回滚能力声明进行校验。
- 仅在 `WorldState` 已恢复后执行回滚回调。
- 仅在世界 bundle 已提交后执行不可逆操作。
- 生命周期回调失败时，将 runtime 标记为终止状态。

验收：失败 bundle 不保留世界写入；可事务或可补偿的 adapter 收到回滚；不可逆操作不会先于后续可失败的世界 effect 执行；生命周期失败后不能再推进第二个 tick。

### 阶段 4：后续单独规划，当前不实施

将现有 social-platform 操作分类为 transactional、compensatable 或 irreversible，并迁移到具体能力分类，是后续独立工作。本轮只提供基础生命周期协议、错误语义和相应测试，不改变现有 social-platform 操作的执行时机或补偿策略。

## 约束

- 决策代码、workflow、recipe 和 reaction 继续产出 effect bundle，不直接写入 `WorldState`。
- `WorldExecutor` 继续拥有世界写入与事务处理职责。
- 本工作不向 `WorldState.services` 新增 key；复用现有 external-runtime bridge 边界。
- Package catalog 保持 runtime-scoped，并在世界执行前冻结。
- 必须区分世界回滚和外部补偿；补偿成功不等于外部系统天然具备事务性。

## 明确不在本轮实施的内容

- 不新增独立的、持久化的 incident log。生命周期错误保留在异常、运行日志和现有内存诊断状态中。
- 发生终止性生命周期失败后，不额外导出用于诊断的 checkpoint；避免形成未声明外部状态不确定性的 archive。
- 暂不迁移并逐项分类现有 social-platform 操作为 transactional、compensatable 或 irreversible。基础协议与校验机制先落地；具体 social-platform 迁移另立计划。
