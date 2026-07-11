# KERN Effect 能力盘点

本文记录 2026-07-11 对当前 Effect 系统的代码级盘点，目的是明确 KERN
已经能表达什么、哪些 Effect 属于稳定原语、哪些已经承担控制流，以及后续扩展
Effect 时应守住的 DSL 边界。

代码仍是事实来源。正式注册表位于 `KERN/effect_contract.py`，当前共注册 43 个
Effect；盘点时所有注册项均能解析到 binder 和 handler。

## 1. 当前执行契约

Effect 的实际执行路径是：

```text
raw effect data
-> effect-specific binder
-> normalized effect data + invocation context
-> WorldExecutor
-> effect-specific handler
-> emitted events or execution error
```

`WorldExecutor` 在单 Effect 前保存 `WorldState` 快照。handler 抛出异常或返回
执行错误时，单 Effect 回滚。Bundle 按顺序执行 Effect，并在任意 Effect 失败时
回滚整个 Bundle。

当前契约的优点：

- LLM、Recipe 和 Reaction 不能直接修改世界。
- binder 负责把数据输入规范化，并显式报告缺失字段。
- handler 隐藏复杂写入规则并返回事件。
- Bundle 是事务边界，成功事件只在提交后进入 settlement。

当前契约尚未表达：

- Effect 是公开场景能力、内核运行指令，还是场景扩展。
- Effect 是否调用 LLM、外部 runtime 或不可回滚副作用。
- Effect 是否允许执行子 Bundle。
- Effect 的稳定性和版本。
- 第三方注册方式。新增 Effect 目前仍需修改中央 `EFFECT_SPECS`。

## 2. 能力目录

### 2.1 Bundle 控制流（3）

| Effect | 当前能力 | 判断 |
| --- | --- | --- |
| `InvokeBundle` | 执行 named、inline 或组件字段中的子 Bundle | 相当于函数调用，是 DSL 控制流 |
| `RandomBundle` | 按权重选择一个分支并执行其子 Bundle | 相当于随机分支，是 DSL 控制流 |
| `ApplyToQuery` | 查询实体并对每行执行子 Bundle | 相当于循环，是 DSL 控制流 |

三者都已纳入父 Bundle 事务，子事件也会保留自己的执行 context。事务语义已经
稳定，但它们使 Bundle 从“顺序 Effect 列表”变成可递归执行图。按当前产品方向，
不应再增加新的通用控制流 Effect；这三项需要单独决定保留、限制或迁移策略。

`RandomBundle` 目前使用进程级 `random`，没有从 runtime 注入可复现随机源。

### 2.2 通用世界写入原语（12）

| Effect | 当前能力 |
| --- | --- |
| `CreateEntity` | 从模板创建实体，放入地点或容器，可覆盖生成名称 |
| `DestroyEntity` | 删除实体、递归删除容器内容，并清理任务和位置引用 |
| `MoveEntity` | 在地点和容器之间移动实体 |
| `ModifyProperty` | 设置或增减组件字段，支持嵌套路径和声明式 clamp |
| `AddTag` | 添加实体 tag，必要时创建 `TagComponent` |
| `RemoveTag` | 删除实体 tag |
| `AddStatus` | 添加状态，可设置到期 tick |
| `RemoveStatus` | 删除状态及到期记录 |
| `SetEnvironmentField` | 设置环境 scope 字段 |
| `AddEnvironmentCondition` | 添加环境条件，可设置到期 tick |
| `RemoveEnvironmentCondition` | 删除环境条件 |
| `EmitEvent` | 生成自定义语义事件，并渲染白名单文本字段 |

这组最接近理想中的默认 DSL 原语：接口较小，行为明确，可以直接组合成 Bundle。
其中 `DestroyEntity` 内部已经是深模块，会处理容器和任务清理；复杂度留在 handler
中是合理的。

`CreateEntity` 当前即使未能放入目标地点或容器，也会保留已注册实体并返回
`EntityCreated(placed=false)`。需要确认“未放置实体”是否是正式世界状态；如果不
是，应把放置失败改为执行错误。

### 2.3 内核维护与时间推进（2）

| Effect | 当前能力 |
| --- | --- |
| `StatusTick` | 清理到期状态并产生到期事件 |
| `EnvironmentConditionTick` | 清理到期环境条件并产生到期事件 |

它们通过 Reaction 接入 tick，但本质上是内核维护指令，不是普通场景作者主动调用
的游戏动作。未来 Effect 目录应明确标为 engine-only。

### 2.4 任务生命周期（11）

| Effect | 当前能力 |
| --- | --- |
| `CreateTask` | 从 Recipe 物化持续任务、时长、progressor 和生命周期 Bundle |
| `AcceptTask` | 将任务分配给 worker 并进入执行态 |
| `ProgressTask` | 增加任务进度 |
| `UpdateTaskStatus` | 更新任务状态并处理进入/离开执行态 |
| `FinishTask` | 执行完成 Bundle、cleanup 并结束任务 |
| `InterruptTask` | 按 task policy 暂停、重置或取消任务 |
| `InterruptCurrentTask` | 找到目标当前任务并发起中断 |
| `ResumeTask` | 恢复可继续的任务并重新执行 start Bundle |
| `CancelTask` | 取消任务并执行 cleanup |
| `ConsumeInputs` | 按当前任务参数消耗输入实体 |
| `WorkerTick` | 计算进度，执行 tick Bundle，并在完成时触发 `FinishTask` |

这组共同构成一个任务领域模块，不能只按独立原子 Effect 理解。`CreateTask`、
`AcceptTask`、中断、恢复和完成之间共享状态机与 task policy。

其中 `WorkerTick` 是 engine-only 调度指令。任务的 `start_bundle`、`tick_bundle`、
`cleanup_bundle` 和 `completion_bundle` 仍然形成受控的子 Bundle 执行点。即使未来
限制普通 Bundle 嵌套，任务生命周期也需要保留这种由内核拥有的组合语义。

### 2.5 Agent、记忆、对话和调试（6）

| Effect | 当前能力 | 判断 |
| --- | --- | --- |
| `AgentControlTick` | 唤醒 workflow，让 Agent 在一个 tick 内决定并执行动作 | engine-only 调度，不是普通世界写入 |
| `AddMemoryNote` | 向角色短期记忆加入文本、重要度和标签 | 可保留的领域 Effect |
| `ApplyMemoryPatch` | 批量更新短期记忆、摘要和日志游标 | workflow 内部同步指令 |
| `StartConversation` | 选择同地点参与者、调用 dialogue provider、记录对话和事件 | 同时混合 LLM 调用、随机顺序、预算和世界记录，需重点重审 |
| `ApplyMetaAction` | 当前只支持切换 interrupt preset | 泄漏内部配置概念，接口过于抽象 |
| `AttachDetails` | 把实体或 preset 详情写入最近一条 interaction log | 更像展示/调试适配器，不像世界 Effect |

`StartConversation` 是一个很深的实现，但当前接口背后混合了决策、随机性、预算、
日志和事件结算。它还使用进程级 `random.shuffle`。需要决定“对话”究竟是一项世界
动作、一个 task，还是独立的 conversation runtime。

`ApplyMetaAction` 的名称很宽，实际只有一个内部操作；`AttachDetails` 依赖“最后一
条 interaction log”这个隐式顺序约束。这两项都不适合作为稳定公开 DSL。

### 2.6 领域级复合 Effect 与系统控制（3）

| Effect | 当前能力 | 判断 |
| --- | --- | --- |
| `KillEntity` | 创建尸体、转移物品、销毁原实体并发出死亡事件 | 合理的领域级深模块，但 corpse 语义不是所有场景通用 |
| `ExchangeResources` | 校验资金和物品，执行销毁/转移、产出和结算 | 合理的领域级深模块 |
| `AbortSimulation` | 写入 abort 状态并请求 runtime 停止 | engine/system 指令 |

这组说明复杂行为不必放进 Bundle。`KillEntity` 和 `ExchangeResources` 在 handler
内部组合较低层写入，调用方只学习一个较小接口，符合深模块方向。

`KillEntity` 是否属于默认 core，取决于 KERN 是否承诺所有场景都有死亡/尸体语义；
否则更适合由生存或角色生命扩展包提供。

### 2.7 社交平台扩展（6）

| Effect | 当前能力 |
| --- | --- |
| `ObserveSocialFeed` | 调用外部 runtime 获取推荐流并更新手机屏幕 |
| `ObserveSocialPost` | 打开屏幕中的帖子并更新屏幕内容 |
| `CreateSocialPost` | 使用屏幕账号创建帖子 |
| `InteractSocialPost` | 点赞、评论、转发等帖子互动 |
| `FollowSocialAccount` | 关注账号 |
| `SocialActivityGateTick` | 筛选社交 Agent，调用 workflow，并支持并行 decide/串行 commit |

前五项是围绕 external runtime seam 的领域适配器，可以作为独立社交平台扩展保留。
其外部 SQLite 写入不参与 `WorldState` 回滚，必须显式标记为 external side effect。

`SocialActivityGateTick` 是 RumorSpread 场景调度器，包含选择 Agent、概率、冷却、
手机检查、provider 路由和批量 LLM 决策。社交平台已不再是项目主线，因此它不应
继续定义核心 Effect 模型；长期应随社交扩展一起移出 core catalog。

## 3. 按未来定位重新分类

建议正式 Effect catalog 增加可见性和副作用元数据，并按以下四层理解：

### Core public

场景数据可以稳定使用的默认能力：实体创建/删除/移动、属性、tag、status、环境、
语义事件，以及经过确认的任务公开操作。

### Engine internal

由 tick、workflow 或 runtime 触发的维护指令：`AgentControlTick`、`WorkerTick`、
`StatusTick`、`EnvironmentConditionTick`、`ApplyMemoryPatch`、`AbortSimulation`。

### Domain extension

具有明确领域语义的深模块：社交平台操作、`KillEntity`、特定交易、未来的战斗、
种植、制作等。它们可以随扩展包注册，不必全部成为 KERN 默认语义。

### Review / legacy

当前存在但不应继续扩张的接口：三个 Bundle 控制流 Effect、`ApplyMetaAction`、
`AttachDetails`，以及当前形态的 `StartConversation`。

## 4. 与“有限 DSL + 自定义 Effect”方向的差距

当前系统已经有合适的执行 seam：binder、handler、事务和事件返回。但还缺一个正式
的第三方扩展 seam。用户若要增加 Effect，必须编辑 KERN 的中央注册表，这意味着
“自己写 Effect”目前仍等同于 fork 内核。

下一步设计应优先回答：

1. 扩展包如何注册 Effect，而不修改 `KERN/effect_contract.py`。
2. 一个 Effect 必须声明哪些输入、事件和副作用属性。
3. 扩展 Effect 如何获得受控的 runtime context。
4. 外部副作用如何标记，是否允许进入可回滚 Bundle。
5. core、engine-only 和 extension Effect 如何在 lint 与文档中区分。
6. 如何防止扩展 Effect 自行发布 Reaction 或绕过 settlement。

建议的最小元数据不是完整脚本类型系统，而是：

```text
effect id
module / binder / handler
visibility: public | engine
origin: core | extension
side_effect: world | external | runtime
allows_child_bundle: true | false
stability / version
```

## 5. 建议处理顺序

1. 冻结 Bundle 为顺序 Effect 列表，不再新增通用控制流能力。
2. 给 43 个 Effect 标记 public、engine、extension、review 分类。
3. 为 Effect 建立正式扩展注册 seam，让复杂需求可以由代码扩展实现。
4. 审查 `InvokeBundle`、`RandomBundle`、`ApplyToQuery` 的现有 Data 使用，再决定兼容策略。
5. 优先重审 `StartConversation`、`ApplyMetaAction` 和 `AttachDetails` 的职责。
6. 将社交平台 Effect 视为扩展能力，不再作为 core 设计依据。
7. 在注册新 Effect 前，要求 binder、handler、事务行为、事件和 targeted tests 同时存在。

这次盘点不改变任何现有 Effect 行为，也不代表立即删除现有数据能力。它为下一步
设计 Effect 扩展契约和收缩 DSL 控制流提供事实基线。
