# KERN 内核契约恢复计划

状态：核心错误与 EffectRecord 契约已实施；领域能力迁移仍在进行
建立日期：2026-07-23
适用范围：`KERN/` 内核运行链、相关测试、Package 能力迁移与失败报告

## 1. 目标

恢复 KERN 作为数据驱动多智能体仿真内核的完整能力，同时重新建立清晰、可验证的模块契约：

- 场景选择决定领域行为，KERN 内核不隐含特定场景世界观；
- Decision、Workflow、Recipe 和 Reaction 不直接修改 `WorldState`；
- Effect Bundle 是一次完整世界事务，失败不会留下部分世界事实；
- 成功事件只在 Bundle 提交后可见；
- 错误在不同模块间无损传递，并由统一策略决定继续、回滚、中止或终止；
- `failure.json` 记录一次运行的完整失败证据，不改变世界事务，也不重新定义错误；
- Checkpoint、Archive 和分析工具只观察已经提交的世界事实。

本计划追求能力迁移和契约恢复，不以删除功能作为完成标准。需要移出内核的能力应进入明确的 capability package，并继续拥有行为测试和 smoke 覆盖。

## 2. 当前验证基线

2026-07-24 契约恢复后的验证结果：

- 19 个新的/改写后的契约测试通过；旧测试中仍有大量与新失败语义冲突的断言；
- `compileall` 通过；
- Camping package lint 为 0 error、0 warning；
- Camping smoke 正常完成；
- 核心 Effect/Component Catalog 已不再暴露已删除的社交平台定义；
- 社交平台实现与 SU7 可运行包已从内核和 Packages 移除，历史研究数据保留在 `research_data/su7_social_platform_legacy/`。

这些结果证明现有测试所覆盖的能力仍可运行。它们不能证明跨模块契约正确；部分测试正在固定错误的局部行为。

当前工作树同时包含用户修改和本次契约恢复修改。恢复工作必须保留并区分用户现有修改，不得通过 reset、checkout 或覆盖文件来整理工作树。

## 3. 权威运行链

目标运行链如下：

```text
runtime config / Package composition
-> data bundle
-> WorldState
-> Decision / Workflow reads a view and returns intent
-> InteractionEngine compiles commands into effect bundles
-> WorldExecutor validates, normalizes, and executes one transaction
-> WorldSettlement publishes committed events
-> Reactions consume committed events and produce new bundles
-> Archive / Checkpoint / FailureReport observe authoritative outcomes
```

每个模块的所有权：

| 模块 | 拥有的责任 | 禁止承担的责任 |
|---|---|---|
| Decision / Workflow | 读取视图、产生决策或命令 | 修改世界、提前宣告动作成功 |
| InteractionEngine | Recipe 匹配、命令到 Bundle 的纯编译 | 执行 Bundle、写 interaction/event log |
| Binder | 验证和规范化 Effect 输入 | 修改世界、选择错误处置策略 |
| WorldExecutor | 世界写入、Bundle 事务、回滚 | 场景决策、提交前发布事件 |
| WorldSettlement | 提交后事件发布、Reaction FIFO 结算 | 绕过 Executor 修改实体状态 |
| Package | 提供领域 Component、Effect、Recipe、Reaction | 修改另一个 Runtime 的 Catalog |
| FailureReport | 保存失败证据和关联上下文 | 改变世界结果、定义另一套错误分类 |

## 4. 必须恢复的不变量

### I-01 事实唯一性

一次动作只有一个权威结果：`committed`、`rejected` 或 `rolled_back`。Interaction log、event log、world state、archive 和 failure report 不得互相矛盾。

### I-02 世界写入唯一入口

Decision、Workflow、Recipe 和 Reaction 只产生数据。所有 `WorldState` 写入，包括 event log、interaction log、任务、记忆和运行状态，必须经过 Executor/Settlement 明确拥有的路径。

### I-03 Bundle 原子性

Bundle 中任一 Effect 失败时，Bundle 内全部世界写入回滚。嵌套 child bundle 属于父事务。外部写入必须依据 `world`、`external_transactional`、`external_compensatable` 或 `external_irreversible` 明确声明。

### I-04 提交后可见性

成功事件、成功 interaction 和 Reaction 输入只能来自已经提交的 Bundle。Attempt 可以记录拒绝或失败，但必须明确标识为 attempt，不能伪装为提交结果。

### I-05 错误无损性

错误跨越 Binder、Executor、Workflow、Settlement、Runtime 和 FailureReport 时，稳定 code、来源、phase 和 cause 不得丢失或被静默改写。

### I-06 场景隔离

KERN 提供组合和执行机制。尸体、营养、生存、交易、社交平台等领域语义只有在被确认是所有世界共同需要的原语时才能保留在核心；否则迁入 capability package。

### I-07 运行时依赖受控

`WorldState.services` 不能继续成为任意依赖总线。新字符串键需要独立设计任务和明确所有者；长期目标是让调用者通过小而明确的 Interface 使用运行能力。

### I-08 Event 与 Interaction 分层

`event_log` 保存 Effect 级、机器可读的已提交结果；`interaction_log` 保存 Recipe 或 Reaction 级、面向 Agent 的自然语言经历。Agent 感知层从完整 interaction 队列中筛选自己能够知道的记录。底层 Event 不能依靠事后黑名单承担自然语言记忆职责。

### I-09 叙事显式且提交后生效

自然语言叙事必须由 Recipe、Reaction 或任务生命周期数据显式提供，并通过统一动态文本模块渲染。成功叙事只能在对应世界修改提交后写入；提前渲染的文本只能作为待确认数据，回滚时必须丢弃。

## 5. 已确认的问题登记

### CR-01 Workflow 提前写入 interaction/event log

严重度：阻断契约恢复
证据：`KERN/agent_workflow/runtime.py`

当前行为：

- `_commands_to_operations()` 在 Bundle 执行前写入成功 interaction；
- `_record_workflow_error_event()` 直接调用 `ws.record_event()`；
- Bundle 后续失败并回滚时，提前写入的成功 interaction 仍然存在；
- `AgentControlTick` handler 忽略嵌套执行产生的错误事件并返回空事件列表，外层 Effect 因而可能被视为成功。

已复现结果：一个包含 `UnknownEffect` 的命令先写入 `status=success`，随后 Bundle 返回 `bundle_rolled_back=True`，成功 interaction 仍保留。

需要决定：

1. Interaction 是由专用 Effect 写入，还是由 Settlement 根据提交结果统一生成；
2. 被 Recipe 拒绝的命令如何表示 attempt；
3. 多命令决策是每条命令一个事务，还是整个决策一个事务；
4. `AgentControlTick` 是否应成为编排入口，而不是普通世界 Effect。

验收标准：

- Workflow 静态扫描不再出现直接 `ws.record_*` 写入；
- Bundle 回滚后不存在 success interaction；
- 拒绝、回滚和提交三种结果有独立行为测试；
- Reaction 只能观察提交后的成功事件。

### CR-02 ExecutorError 结构不完整且默认分类失真

严重度：高
证据：`KERN/execution_errors.py` 和多个 `KERN/executor/_effect_*.py`

当前行为：

- 约 50 个 handler 手写只有 `type` 和 `message` 的 `ExecutorError`；
- 缺少 kind 的错误被默认解释为 `business`；
- contract、engine 和正常业务拒绝因此可能获得相同处置；
- 部分无效 Bundle 使用默认 `executor_error()`，被错误标记为可恢复业务错误。

需要决定统一错误模型，建议至少包含：

```text
code          稳定机器代码，必填
category      business | contract | engine | infrastructure
origin        binder | executor | workflow | interaction | reaction | llm | external_runtime | persistence
disposition   reject_action | rollback_bundle | abort_run | terminal
retryable     true | false
message       面向人的摘要
cause         可选的原始错误链
context       结构化定位信息
```

验收标准：

- 内核中不存在手写的不完整 `BindError`/`ExecutorError`；
- 每个错误都具有稳定 code；
- 不再通过缺省值把未知错误降级为 business；
- schema/constructor 测试覆盖所有 Effect handler 返回的错误。

### CR-03 Workflow、Executor、Reaction 和 Runtime 的处置策略不一致

严重度：高

当前行为：

- Workflow contract error 可以 fail-fast；
- Workflow 的普通 Python 异常可能被转换成 noop；
- 普通 Agent Action 的 ExecutorError 通常只停止本轮行为；
- 相同 ExecutorError 出现在 Reaction 中会停止整场模拟；
- External runtime lifecycle failure 会把 Runtime 标记为 terminal；
- `recoverable` 字段没有统一策略消费者。

需要建立唯一错误处置矩阵。错误后果必须由错误内容和显式 runtime policy 决定，不能由偶然调用路径决定。

验收标准：

- 为 category × disposition 建立明确矩阵；
- Workflow 编程异常不能静默变成合法 noop；
- 同一错误在顶层、child bundle 和 Reaction 中保持同一错误身份；
- fail-fast 与 degrade 策略只改变处置，不改变错误事实；
- terminal runtime 不能继续推进 tick。

### CR-04 旧 Diagnostics 正在重新定义错误并侵入 WorldState services（已由 FailureReport 取代）

严重度：高，当前改动不得直接落地

当前行为：

- 旧 Diagnostics 使用 `business/llm_output/grounding/kernel/infrastructure`；
- Executor 使用 `business/contract/engine`；
- Workflow 使用 `temporary/business/contract`；
- `engine`、`contract` 等值进入旧 Diagnostics 后可能被归并为 `kernel`；
- `diagnostic_recorder` 曾被添加为新的 `WorldState.services` 字符串键；
- Workflow 通过 WorldState 获取运行设施，扩大了隐式 Interface。

需要决定：

1. FailureReport 是否只接收统一 Failure 的只读投影；
2. LLM request/response context 由谁建立、保留和释放；
3. FailureReport 如何注入，且不成为 WorldState 世界数据的一部分；
4. 文件写入失败为何永远不能影响世界事务；
5. 哪些敏感信息绝不允许进入诊断文件。

验收标准：

- FailureReport 不拥有独立 category 词表；
- 错误进入 failure report 后字段无损；
- 不新增未经设计的 `WorldState.services` key；
- failure report 写入失败不改变世界结果；
- secret redaction 和上下文生命周期测试保留。

### CR-05 核心仍包含具体领域政策

严重度：高

已确认的明确候选：

- `KillEntity` 默认创建 `Corpse` 模板；
- 内核生成中文尸体名称并搬运遗物；
- `CorpseSightedRule` 硬编码 `corpse/dead_body` 标签；
- `LowNutritionRule`、`CreatureComponent`、`EdibleComponent` 等生存领域定义仍在核心 Catalog；
- 交易、装备和价值相关 Component/Effect 也需要依据“最小内核”定义复核。

需要先区分机制和政策：

- 机制候选：DestroyEntity、CreateEntity、MoveEntity、ModifyProperty、EmitEvent；
- 政策候选：死亡生成尸体、遗物归尸体、低营养中断、食物恢复营养。

验收标准：

- 建立核心 Effect/Component 保留清单及理由；
- 领域政策迁入 capability package；
- Package 未选择时相关定义不进入运行时 Catalog；
- Camping 通过显式选择 capability package 恢复全部既有能力；
- Package lint、checkpoint、archive 和 restore 覆盖迁移后的类型。

### CR-06 当前测试偏向局部行为，没有保护跨模块不变量

严重度：高

当前例子：

- 测试断言命令编译后已有 interaction narrative，却没有执行并验证 Bundle 提交；
- 旧 Diagnostics 测试把 `engine -> kernel` 的有损映射固定为预期；
- 现有绿色基线没有检查 Workflow 是否直接修改 WorldState；
- 没有统一扫描所有 handler 的错误 schema。

验收标准：

- 测试 seam 与真实运行 seam 一致；
- 增加跨模块 transaction/settlement 行为测试；
- 增加禁止越权写入和核心场景泄漏的契约测试；
- 删除或改写固定错误行为的测试，而不是在新结构外继续兼容旧错误。

### CR-07 event_log 与 interaction_log 的语义和生产路径混杂

严重度：阻断契约恢复

当前行为：

- `event_log` 预期保存机器可读的世界事实，但 Agent 记忆仍直接读取并通过 `DROP_EVENT_TYPES` 黑名单过滤；
- `interaction_log` 预期保存自然语言经历，却同时包含 Workflow 提前写入、对话、Travel 特例和 Reaction 内部运行记录；
- `WorldSettlement` 会把所有 Reaction 的 triggered/applied 记录写入 interaction，记忆层随后又丢弃所有 `is_reaction=True` 的记录；
- interaction 写入时可能已经保存 `narrative`，记忆层仍根据 `recipe_id` 再次渲染；
- `AttachDetails` 通过“修改最后一条 interaction”追加信息，缺少稳定记录 ID。

用户确认的方向：

- event 粒度是 Effect；interaction 粒度是一次 Recipe 或 Reaction；
- World 保存完整 interaction 队列，Agent Workflow/感知模块负责判断角色能够知道哪些记录；
- 增加专用的 interaction 写入 Effect，使 interaction 世界写入经过 Executor；
- 任务相关的开始、完成等 interaction 由场景或扩展开发者在相应任务 Bundle 中显式编写该 Effect；
- Agent 的自然语言经历主要来自 interaction，不再依赖读取底层 event 后用黑名单排除噪声。

仍需决定：

- 专用 Effect 的正式名称、字段和 binder 契约；
- Recipe/Reaction 的 narrative 是由运行时自动转换成该 Effect，还是要求数据作者显式放入 Bundle；
- 合理业务拒绝是否同时产生结构化 Event 和自然语言 interaction。

验收标准：

- Workflow、Settlement 和普通系统代码不再直接调用 `ws.record_interaction_attempt()`；
- 回滚 Bundle 不留下 success interaction；
- interaction 具有稳定来源 ID，不通过列表最后位置更新；
- Agent 记忆输入测试证明 event 与 interaction 的职责已经分离。

### CR-08 KERN 没有显式建模 Action

严重度：高

当前行为：

- KERN 已有 Command、Recipe、Reaction、Bundle、Effect 和 Event，但没有对象表示“一次有业务意义的行为”；
- Recipe 和 Reaction 都可以执行一个或多个 Effect，但无法统一关联它们产生的 Event 和最终 interaction；
- 耗时 Recipe 会跨越任务创建、逐 tick 推进和完成阶段，当前没有稳定身份贯穿这些时点。

用户提供的定义方向：

- 一次 Recipe 执行或一次 Reaction 执行属于 Action 粒度；
- Action 负责关联业务定义、根 Bundle、Effect 事件和可选 interaction；
- Action 不等同于单条 Effect，也不等同于一次 LLM decision。

仍需决定：

- Action 是否成为正式运行时数据结构，还是仅作为执行上下文中的稳定 ID；
- Action 的状态集合以及 Recipe 合理拒绝是否创建 Action；
- 耗时任务是一个跨 tick Action，还是开始与完成两个 Action；
- checkpoint/archive 是否持久化 Action 身份。

### CR-09 扩展 Effect 的事件契约未定义

严重度：高

当前行为：

- Effect handler 可以返回任意数量和任意结构的事件；
- 第三方开发者可以把复杂业务脚本封装为自定义 Effect，内核无法推断其业务结果；
- 部分 Effect 返回多个业务事件，部分返回空列表，部分错误结构不完整；
- 当前 event log 只知道 handler 实际返回了什么，不能保证每次 Effect 执行都可追踪。

用户确认的约束：

- event_log 的归属粒度是 Effect；
- 内核不能预设自定义 Effect 必须产生哪一种业务事件或有哪些业务字段。

仍需决定：

- 是否要求每个成功 Effect 至少返回一个事件；
- 返回空事件时，内核是否补充只含 Effect 名称和执行身份的通用 `EffectExecuted`；
- 一条 Effect 返回多个业务事件时，是每条事件分别入队，还是使用一个包含子事件的 Effect 结果；
- EffectCatalog/EffectSpec 是否声明事件 schema，扩展包 lint 如何验证；
- event log 的通用外壳应包含哪些稳定字段，业务 payload 保留多大自由度。

### CR-10 Reaction 缺少正式的 Agent 叙事声明

严重度：高

当前行为：

- Reaction 数据主要只有 `id/on_event/selector/condition/bundle`；
- 代码会读取 `reaction_verb`，但它只用于内部 triggered/applied interaction 标签；
- Reaction 没有与 Recipe `narrative_success` 对等的自然语言字段；
- 流程控制 Reaction 和角色可感知 Reaction 没有正式区分。

用户确认的方向：

- Reaction 可以提供 `narrative_success`；
- 只有提供 `narrative_success` 的 Reaction 才产生 action 级 interaction；
- 流程控制 Reaction 通常不提供 narrative，因此不进入 Agent 经历；
- Reaction 不提供 `narrative_fail`；Reaction Bundle 执行失败属于严重错误，需要中断模拟并进入错误处置流程。

仍需决定：

- Reaction narrative 如何转换成专用 interaction Effect；
- narrative 的 actor、target、地点和其他动态引用从 trigger event/context 中如何取得；
- Reaction interaction 是否需要 importance/topic 等感知元数据。

### CR-11 动态文本存在两套不兼容的软契约

严重度：高

当前行为：

- Recipe narrative 使用 `{actor}`、`{target}`、`{reason}`，由 Workflow 中的专用字符串替换实现；
- `KERN.dynamic_text` 使用 `{self.entity_name}`、`{target.entity_name}`、`{event.*}` 和 `{param:*}`；
- Recipe 中 `{target}` 表示目标名称，而独立动态文本模块中 `{target}` 表示目标 ID；
- JSON 作者无法从 schema/lint 得知某个位置允许引用哪些对象和字段；
- 如果提交后才渲染，`DestroyEntity` 等 Effect 可能已经删除 narrative 引用的目标。

用户确认的方向：

- Recipe、Reaction 和 interaction Effect 应复用独立动态文本渲染模块；
- 动态文本保持只渲染一次，不递归解释渲染结果；
- JSON 可用引用必须形成显式、可 lint 的作者契约。

仍需决定：

- Recipe、Reaction 和任务生命周期分别向渲染器提供哪些上下文；
- 是否迁移到统一的 `{self.*}/{target.*}/{event.*}/{param:*}` 语法，旧 `{actor}/{target}/{reason}` 如何兼容；
- narrative 在执行前渲染并提交后落盘，还是建立不可变的对象快照后提交后渲染；
- 是否以及如何暴露任意自定义 Effect 的执行结果给 action narrative。

### CR-12 Bundle 的作者语义与运行时追踪身份不足

严重度：中高

当前行为：

- `EffectBundle` 目前只是一个 Effect 列表；
- Bundle 同时承担原子事务、内联打包、命名复用和嵌套调用用途；
- `InvokeBundle`、任务生命周期 Bundle 和临时单 Effect Bundle 可以形成嵌套，但事件没有稳定 bundle ID、父 bundle ID 或路径；
- Recipe/Reaction 当前读取显式 `bundle.effects`，对直接放在定义下的 Effect 没有统一规范化规则。

用户同意的方向：

- event log 保持平坦，不把整个嵌套树复制到每条记录；
- 通过 `bundle_id`、`parent_bundle_id` 或等价路径信息恢复嵌套关系。

仍需决定：

- Bundle 的唯一正式语义是否收敛为“共同提交或共同回滚的事务边界”；
- 没有显式 Bundle 的 Effect 是否自动包装成单 Effect Bundle；
- 命名 Bundle 是作者复用机制还是稳定业务身份；
- 运行时 bundle ID 和 JSON 定义 ID 如何区分。

### CR-13 任务的 interaction 生命周期依赖特例

严重度：高

当前行为：

- Task 实际保存 `start_bundle`、`tick_bundle`、`cleanup_bundle` 和 `completion_bundle`；
- 每 tick 先执行 `ProgressTask`，再执行 `tick_bundle`，完成时执行 Recipe 的 completion Bundle；
- Recipe 的单个 `narrative_success` 通常描述任务开始；
- Travel 完成 interaction 由 `FinishTask` handler 硬编码，其他任务没有统一完成叙事。

用户提供的方向：

- 任务至少存在推进和完成两个重要执行时点；
- 任务相关 interaction 使用专用 interaction Effect；
- 场景或扩展开发者在希望记录的任务生命周期 Bundle 中显式提供该 Effect 数据；
- 逐 tick 进度可以只产生 Effect/Event，不要求每 tick 产生自然语言 interaction。

仍需决定：

- 开始、完成、中断、恢复分别是否需要独立 interaction；
- 一个耗时任务对应一个 Action 还是多个阶段 Action；
- interaction Effect 如何引用 Task、原始 Recipe、worker 和 completion Effect 结果；
- 移除 Travel 特例后的数据迁移和兼容策略。

## 6. 建议解决顺序

顺序依据是依赖关系，不代表已获得实施授权。

### 阶段 A：确定事实和事务 seam

1. 联合处理 CR-01、CR-07、CR-08；
2. 明确 Command、Action、Bundle、Effect、Event 和 Interaction 的关系；
3. 定义专用 interaction Effect 的最小契约；
4. 明确 command、attempt、rejected action 和 committed interaction 的术语；
5. 确定 AgentControlTick 的编排位置；
6. 用回滚测试锁定事实唯一性。

如果不先完成这一阶段，后续错误和 failure report 都不知道应关联“尝试”还是“提交结果”。

### 阶段 B：统一错误模型与处置

1. 解决 CR-02；
2. 解决 CR-03；
3. 迁移所有 Binder、Handler、Workflow、Reaction 和 External runtime 错误；
4. 删除错误分类的隐式缺省和字符串猜测。

### 阶段 C：接入 FailureReport

1. 解决 CR-04；
2. FailureReport 消费统一 Failure；
3. 保留未经脱敏的 LLM 失败证据和 best-effort 文件写入能力；
4. 不通过新的 WorldState service key 建立耦合。

### 阶段 D：迁移领域能力

1. 解决 CR-05；
2. 先迁移 Corpse/Death 这组边界最明确的能力；
3. 再审查 Survival、Economy、Conversation 等候选；
4. 每次迁移后恢复对应 package smoke，而不是删除能力。

### 阶段 E：收紧测试和文档

1. 解决 CR-06；
2. 更新配置详解和开发者上手文档；
3. 增加稳定的架构契约测试；
4. 运行完整本地基线。

### 阶段 F：补齐 Action、叙事与扩展契约

1. 解决 CR-09，定义扩展 Effect 的事件责任和内核通用外壳；
2. 解决 CR-10，增加 Reaction 可选 `narrative_success`；
3. 解决 CR-11，统一动态文本输入和 lint；
4. 解决 CR-12，增加 Bundle 运行时父子追踪；
5. 解决 CR-13，用数据化 interaction Effect 替换 Travel 等任务特例。

## 7. 每个问题的工作协议

开始任何一项实现前，先和用户确认：

1. 预期结果；
2. 受影响模块和不受影响模块；
3. 要保留的兼容行为；
4. 必须先变红的行为测试；
5. 验收命令；
6. 是否涉及 Package 数据迁移或 checkpoint 兼容。

实现时：

- 先写能捕获具体契约破坏的测试；
- 一次只改变一个 seam；
- 不为旧的错误结构增加新的兼容层；
- 不顺手增加新的 `WorldState.services` key；
- 不修改无关的用户工作树内容；
- 场景能力迁移必须同时提交 package、catalog、codec 和测试。

完成时记录：

- 实际修改；
- 验证结果；
- 困难和剩余风险；
- 是否改变 checkpoint/archive schema；
- 下一项是否已经具备前置条件。

## 8. 完整恢复验收

最低验收命令：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.package.smoke.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.package.smoke.json
```

此外必须证明：

- 回滚 Bundle 不留下成功 interaction 或部分世界写入；
- 所有运行时错误符合统一 schema；
- Workflow 和 Reaction 不直接修改 WorldState；
- FailureReport 不改变世界事务；
- 未选择 capability package 时，相关领域定义不进入 Catalog；
- 选择所需 capability package 后，Camping 保持现有能力；
- Checkpoint restore、Archive 和 runtime snapshot 仍可复现相同提交状态。

## 9. 已登记的多 command 事务决定

先讨论 CR-01：一次 Agent 决策输出多个 commands 时，KERN 应采用哪一种原子性？

候选语义：

### 方案 A：每条 command 一个独立事务

- 前一条成功 command 会提交；
- 后一条失败不会撤销前一条；
- 每条 command 分别产生 committed/rejected/rolled_back interaction；
- 适合连续行动，但决策整体不是原子的。

### 方案 B：整个 decision 是一个事务

- 所有 commands 编译成一个 Bundle；
- 任一 command 失败则全部回滚；
- interaction 只在整个 decision 提交后发布；
- 原子性最强，但长决策更容易整体失败。

这个决定仍未完成。CR-01 的实现还依赖 CR-07 至 CR-13 中列出的 Action、interaction Effect、事件外壳和动态文本契约，不能只移动现有日志写入位置。

## 10. 本轮讨论确认的设计方向

以下内容来自用户明确提出或同意的产品方向。它们用于约束后续设计，不代表具体 API、schema 或兼容策略已经完成。

### D-01 两种日志采用不同粒度

- `event_log` 是 Effect 级、机器可读的执行结果历史；
- `interaction_log` 是 Action 级、面向 Agent 的自然语言经历；
- 一次 Recipe 执行或一次 Reaction 执行属于 Action 粒度；
- 一条 Effect 可以由扩展开发者实现为复杂脚本，内核不能替它猜测业务事件结构。

### D-02 interaction 通过专用 Effect 写入

- 增加专用的 interaction 写入 Effect；
- interaction 因而服从 Binder、Executor 和 Bundle 回滚规则；
- success interaction 必须与其对应世界修改共同提交，或在确认提交后执行；
- Workflow、Settlement 和任务 handler 不再直接写 `WorldState.interaction_log`。

具体 Effect 名称和字段尚未决定。

### D-03 Recipe 与 Reaction 的叙事规则

- Recipe 可以提供 `narrative_success` 和 `narrative_fail`；
- Reaction 可以提供 `narrative_success`；
- 没有 `narrative_success` 的 Reaction 不写 interaction，适用于流程控制规则；
- Reaction 不提供 `narrative_fail`；Reaction 执行失败属于严重错误并中断模拟；
- Reaction narrative 最终也应通过专用 interaction Effect 落盘，自动转换还是显式 Effect 尚未决定。

### D-04 Agent 感知在 Workflow 一侧完成

- World 保存整个模拟产生的 interaction 队列；
- interaction 记录保留 actor、target、location、来源和自然语言等事实；
- Agent Workflow/感知模块根据角色关系、地点和后续可见性规则筛选；
- 流程控制是否进入队列由 narrative 是否存在决定，不依赖记忆层黑名单补救。

### D-05 动态文本使用统一模块

- Recipe、Reaction、任务 interaction 和其他明确支持的文本字段复用独立动态文本渲染模块；
- 文本只渲染一次；
- JSON 作者可以引用的对象和路径必须形成显式软契约，并由 lint 尽可能验证；
- 当前 `{actor}/{target}/{reason}` 与 `{self.*}/{target.*}/{event.*}/{param:*}` 的冲突必须解决后才能迁移。

### D-06 Bundle 事件采用平坦存储和父子追踪

- event log 不直接保存递归 Bundle 树；
- 每条 Effect/Event 记录携带运行时 `bundle_id`；
- 嵌套执行通过 `parent_bundle_id`、路径或等价字段恢复；
- Bundle 首先是共同提交或共同回滚的候选边界，其复用和作者语义仍需继续澄清。

### D-07 任务 interaction 由数据作者放在生命周期时点

- Task 已有开始、逐 tick、清理和完成 Bundle；
- 场景或扩展开发者在需要产生自然语言经历的生命周期 Bundle 中编写专用 interaction Effect；
- 逐 tick 推进可以只产生 event，不默认产生 interaction；
- Travel 完成时的硬编码 interaction 应由通用数据方式替代。

## 11. 当前仍未决定的设计问题

在开始实现新增日志能力前，仍需依次决定：

1. Action 是正式持久化对象，还是执行期间的关联 ID；
2. 专用 interaction Effect 的输入字段、动态文本模板和提交时机；
3. 自定义 Effect 返回事件的最低要求，以及空事件时是否补 `EffectExecuted`；
4. Effect 返回多个事件时的 event log 结构；
5. 统一动态文本模块对 Recipe、Reaction 和 Task 分别开放哪些引用；
6. narrative 是执行前渲染后等待提交，还是基于不可变快照在提交后渲染；
7. 没有显式 Bundle 的 Effect 是否规范化为单 Effect Bundle；
8. 耗时任务是一个跨 tick Action，还是开始和完成两个 Action；
9. 多 command decision 采用独立事务还是整体事务；
10. 新增 Action/Event/Interaction 身份是否改变 checkpoint、archive 和 runtime snapshot schema。
