# KERN 内核待决事项

最近按实现复核：2026-08-12。

本文只记录当前代码仍存在的设计或质量缺口。已完成迁移和历史讨论由 git 历史保存，不在
此处重复。处理任何条目前，应重新读取相关实现和测试。

## 1. Failure 身份质量

部分 Handler 仍通过默认 `EXECUTOR_FAILURE` 报错。需要为可区分的契约、业务和执行失败
分配稳定 code，并增加扫描或契约测试，保证所有 Handler failure 都能序列化为完整
`KernFailure` schema。

验收：核心 Handler 的失败路径有稳定机器身份；未知 Python 异常仍保留 cause 和 traceback。

## 2. Interaction 可见性与 Action 关联

当前 interaction 在提交时生成 `interaction_id`，记录 Action 和 Bundle 上下文，并写入当时
可感知 Agent 的 inbox。剩余设计是定义参与者、同地点、私有和未来远程传播之间的稳定
可见性等级，以及明确一个 Action、跨 tick Task、Event 和多条 interaction 的关联规则。

验收：可见性不是散落的特殊判断；关联字段具有稳定含义并覆盖 checkpoint restore。

## 3. 核心领域政策迁移

核心仍包含 Camping/生存领域倾向较强的能力，例如 `KillEntity` 的 Corpse 行为、
`CorpseSightedRule`、`LowNutritionRule`、Creature、Edible、Equipment、交易和价值能力。
需要逐项决定哪些属于通用内核，哪些迁入显式 capability Package。

耦合风险：未选择对应 capability Package 时，核心 catalog 仍会暴露部分领域 definition，
导致“通用内核”和“Camping 示例能力”的边界不够清楚。新增场景开发者可能误以为这些生存能力
是每个 KERN runtime 的基础语义。

验收：未选择 capability Package 时，领域 definition 不进入 runtime catalog；选择后 Camping
行为和恢复兼容性保持清晰。

## 4. Typed runtime context

`WorldState.services` 仍承载 executor、workflow、provider 和 external runtime 的运行依赖。
需要设计小型显式 Runtime Interface，并给现有字符串键保留清楚的兼容边界。在完成专项
设计前不增加新 service key。

耦合风险：任意知道字符串 key 的模块都能跨层访问 runtime 服务，例如 settlement execute
callback、external runtime bridge 或 workflow registry。这个依赖袋是当前最大的模块耦合点；
迁移前应把允许的 key、调用方向和生命周期写成稳定兼容边界。

验收：系统代码依赖明确接口；兼容层集中且有测试。

## 5. FailureReport 输出隔离

`FailureReportWriter` 对一个 writer 只写一次，但多个 runtime 共用同一 checkpoint 目录时，
它们会竞争同一个 `failure.json`。需要确定 run-scoped 目录或索引规则。

验收：同一输出根目录下的多个 runtime 报告可以独立定位，写入失败不改变世界结果。

## 6. Action 持久化模型

当前 Action 是 turn 内生成的稳定 ID，不是 checkpoint 中的正式对象。需要决定是否保持这一
轻量模型，或引入持久化 Action 生命周期；同时明确 rejection 是否创建 Action，以及跨 tick
Task 是否延续原 Action。

验收：根 Bundle、EffectRecord、interaction 和 Task 对 Action ID 的使用规则明确，恢复行为
有测试。

## 7. 动态文本与 Task narrative 作者契约

动态文本当前只在明确支持的字段中渲染一次。仍需补齐这些字段的作者清单、lint 可验证路径、
实体被销毁后的名称快照规则，以及 Task start/tick/cleanup/completion 哪些阶段应由场景显式
产生 `RecordInteraction`。

验收：文档和 lint 与支持字段一致；Task narrative 不依赖核心硬编码。

## 8. 扩展 Event 与 Bundle 契约

扩展 Effect 已有统一 Event envelope，但 Package 是否声明领域 fact schema、多个 fact 的顺序
约束、命名 Bundle ID 与运行时 Bundle ID 的区别，以及 lint 应检查的扩展契约尚未确定。

验收：自定义 Effect 的输出、空输出、父子 Bundle 关系和 lint 责任有明确规则及聚焦测试。

## 9. Agent Workflow 输入只读边界

`TurnRunner` 只把当前 `ws`、`TurnStart`、`TurnFrame` 交给 workflow。`TurnFrame` 不再包含
内核构造的 perception 或 action catalog。默认 LLM workflow 在自身内部调用 observer 和
`memory_policy`；其他内置 workflow 可以直接读取当前 runtime 已加载的核心或 Package 组件。

目标边界：

```text
RecordInteraction
-> PerceptionComponent.interaction_inbox
-> Workflow 读取 inbox 和当前 memory
-> Workflow 决定 memory patch 或 action
-> TurnRunner 执行 workflow 产出的 internal/action bundle
-> WorldExecutor 写入 WorldState
-> WorldSettlement 发布 committed events 并结算 reactions
```

系统内部可以运行 EffectBundle，但必须仍在 executor、transaction 和 event record 边界内：

- Action bundle：由 `SubmitAction` 经 `InteractionEngine` 编译产生。
- Reaction bundle：由 committed Event 匹配 Reaction 规则产生。
- Internal bundle：由 runtime、task lifecycle、conversation 或 workflow bookkeeping 显式产生。

Internal bundle 不是普通 Python 写状态的许可。它只说明该 bundle 不代表一个场景 action 或
reaction；世界写入仍必须通过 Effect binder 和 handler。

当前灰区：workflow bookkeeping 已经会通过 internal bundle 写入记忆，例如 memory consolidation
路径触发 `ApplyMemoryPatch`。这条路径仍经过 executor、transaction 和 event record 边界，但它
让 workflow 不再只是“返回场景 ActionIntent”。后续应明确 internal workflow step 的 contract，
包括允许的 effect 类型、trace/source 标识、失败语义和测试口径。

验收：workflow 对 `ws` 只读；workflow memory 写入仍通过 `ApplyMemoryPatch` effect 和
executor 落地，其他世界写入仍通过 ActionIntent、EffectBundle 和 WorldExecutor 落地。

## 10. 内置 workflow 与场景归属

`social_platform` 目前是源码内置 workflow kind，通过
`KERN.agent_workflow.builtin_workflows.BUILTIN_WORKFLOW_BUILDERS` 注册，并读取已加载 world
Package 的 study data。这个实现让海平面实验能复用内核 TurnRunner、LLM trace、failure report
和 workflow registry，但也把具体实验 workflow 放进了内核源码注册表。

耦合风险：如果社交实验继续演化，内核会逐步承担实验字段、调度文件和决策 prompt 的变化成本。
长期应在以下路径中二选一：

- 保持它是 KERN 内置示例 workflow，并明确其稳定支持范围；
- 设计显式 workflow extension 机制，把 scenario-specific workflow 迁到 Package 或 application
  层，同时保留 runtime-scoped registry 和 fail-fast provider 解析。

验收：新增实验 workflow 不需要改动无关内核模块；Package/app workflow 的注册、identity、
restore 和测试边界清楚。

## 11. 文档边界词与实现状态

近期开出的多个边界已经实现到半稳定状态，但文档里如果只写抽象原则会误导开发者：

- `ActionRejected` 不写错误 Event，也不进入 Reaction FIFO，但会写
  `interaction_origin="action_rejection"` 的 rejected interaction。
- `EffectBundle.record.mode="auto"` 已实现，会经 effect recorder 写入 Agent record inbox；
  `record.mode="template"` 结构上可解析，但 executor 明确拒绝。
- `failure.json` 是完整开发者证据，不脱敏，会保留 runtime config 和可能的凭据。
- runtime 持久化同时包含 `runtime_snapshot.v2`、`run_archive.v1`、`run_snapshot.v1`、
  `run_delta.v1`、`simlog.v1`、`kern_failure.v1`，不能用一个“checkpoint schema”概括。

验收：稳定文档用实现状态表或明确限定词说明“已实现、部分实现、未实现”；中间审计文件中的
稳定结论及时迁移，临时文件不长期作为入口。

## 12. 已知但暂不处理的约束

以下事项已复核，当前保留为明确的产品/研究取舍。它们不应被误报为 Camping 数据缺失；若运行
边界改变，必须在改动前重新评估。

### 12.1 Action 目标可见性

InteractionEngine 可以通过任意已知实体 ID 解析 action target。当前 LLM/grounder 只接收
Agent 可见实体，且已验证不会操作不可见实体，因此暂不在内核增加额外的 runtime 可见性准入。

该取舍不适用于不受信任的外部 action 输入、人工控制接口或会暴露全局实体 ID 的 workflow。
引入这些入口前，应设计统一的 action target access predicate，并覆盖关闭容器、跨地点和私有
背包情形。

### 12.2 RandomBundle 精确重放

`RandomBundle` 当前使用进程随机源，不维护 runtime seed 或 checkpoint RNG 状态。LLM 本身也
具有随机性，当前研究运行不承诺从同一 checkpoint 重放出完全相同的随机产出。

若未来需要确定性 Monte Carlo 对照、checkpoint 分支比较或逐 tick 精确复演，应设计
runtime-scoped RNG，并把其状态纳入 checkpoint 与 archive 契约。
