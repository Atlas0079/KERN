# KERN 内核契约恢复计划

状态：核心执行、失败和 EffectRecord 契约已落实；当前工作集中在剩余设计缺口、领域能力迁移和测试迁移。

建立日期：2026-07-23
最近复核：2026-07-24
适用范围：`KERN/` 运行链、Package 组合、事件与 interaction、失败报告及跨模块契约测试。

本文是当前问题清单。早期问题登记中的“当前行为”描述了历史缺陷，不能继续当作现状；每项问题都必须以本文的状态和代码为准。

状态标记：

- `已吸收`：新架构已经消除了原问题的主要风险。
- `部分遗留`：核心机制已经存在，但仍有明确的边界缺口。
- `未解决`：仍需要设计决定或代码迁移。
- `已过时`：后续产品决定已经使原问题失去原来的意义。

## 1. 当前权威运行链

```text
runtime config / Package composition
-> data bundle
-> WorldState
-> Decision / Workflow 读取视图并产生意图
-> InteractionEngine 将命令编译为 Effect Bundle
-> WorldExecutor 绑定、规范化并执行一个事务
-> WorldSettlement 发布已提交的 EffectRecord
-> Reaction FIFO 消费已提交记录并产生新的 Bundle
-> Archive / Checkpoint / FailureReport 观察权威结果
```

模块所有权：

| 模块 | 允许承担的责任 | 不应承担的责任 |
|---|---|---|
| Decision / Workflow | 读取视图、产生决策或命令 | 修改 `WorldState`、预先宣告成功 |
| InteractionEngine | Recipe 匹配、命令到 Bundle 的纯编译 | 执行 Bundle、直接写日志 |
| Binder | 校验并规范化 Effect 输入 | 修改世界、决定错误处置 |
| WorldExecutor | 世界写入、事务、回滚、EffectRecord 生成 | 场景决策、提交前发布事件 |
| WorldSettlement | 提交后发布记录、Reaction FIFO | 绕过 Executor 修改实体 |
| FailureReport | 保存一次运行的失败证据 | 改变世界结果、重新定义错误模型 |
| Package | 提供场景 Component、Effect、Recipe、Reaction | 修改其他 Runtime 的 Catalog |

## 2. 已落实的基础契约

### 2.1 失败语义

- `KernFailure` 是跨 Binder、Executor、Workflow、Reaction、External Runtime、Persistence 和 Runtime 的统一致命异常。
- `KernFailure` 在 Bundle 内抛出时会回滚包含它的 Bundle；无 Bundle 的 Workflow、Persistence 或 Runtime 失败直接使 Runtime 进入 terminal 状态。
- 失败报告每个 Runtime 最多写一个 `failure.json`，保留 traceback、cause、规范化输入和上下文。
- 报告写入失败不会改变世界事务。
- WorldState 回滚不等于外部世界回滚；外部 transactional、compensatable 和 irreversible Effect 必须显式声明，irreversible 写入延迟到 Bundle 末尾，生命周期通知失败不能伪装成成功。
- 用户已明确要求开发者可见的原始错误信息不脱敏，因此 secret-redaction 不再是本项目的契约要求。
- 合法但当前不可执行的命令使用 `ActionRejected` 值返回；它不是错误，也不会伪装成成功事件。

### 2.2 Effect 与事件

- Binder 规范化后的 Effect 输入只在 Handler 成功后进入 `EffectRecord`。
- `EffectRecord` 保存 Effect 名称、规范化输入、上下文、Bundle 追踪信息和 Handler facts。
- Handler 没有返回业务 fact 时生成通用 `EffectExecuted`。
- 一个 Effect 返回多个 fact 时，事件流中产生多个平坦记录，每条记录保留同一个 Effect 身份。
- `WorldExecutor` 只返回结果；`WorldSettlement` 在 Bundle 成功后写入 `event_log` 并将记录放入 Reaction FIFO。

### 2.3 Interaction 与 Reaction

- `RecordInteraction` 和 `UpdateInteractionDetails` 是专用 Effect，interaction 写入服从 Bundle 回滚。
- Workflow、Settlement 不再直接写入成功 interaction。
- Recipe 和 Reaction 只有在定义了 `narrative_success` 时各自产生一条 interaction；缺少该字段不产生 interaction。
- Agent workflow view 只提供按 actor、target、location 和 private 标记筛选后的 interaction delta，不提供 `event_log` 或 `event_delta`。
- Reaction 的匹配顺序为：`on_event/on_effect -> selector -> condition -> bundle`。
- Effect 触发的 Reaction 只能消费已经提交的 EffectRecord；`WorldTickAdvanced`、`AdvanceTick` 等生命周期事件是 Settlement 有意注入的原始触发事件。
- Bundle 记录携带 `bundle_id`、`parent_bundle_id` 和 `effect_index`，事件日志保持平坦。

## 3. 原问题重新分类

| 原问题 | 当前状态 | 现在的含义 |
|---|---|---|
| CR-01 Workflow 提前写日志 | 部分遗留 | 提前成功日志已消失；拒绝 attempt 表示和多 command 事务粒度仍未决定 |
| Decision 结果分类 | 部分遗留 | 当前把 InteractionEngine 的部分 `failed` 结果归为 rejection；需要区分合法不可执行动作与 contract/runtime 错误 |
| CR-02 ExecutorError 结构 | 部分遗留 | 统一 Failure 已存在；大量 Handler 仍使用通用错误码，完整 schema 约束不足 |
| CR-03 错误处置矩阵 | 已过时 | “所有错误终止模拟”使原来的继续、降级、恢复矩阵失去主要意义 |
| CR-04 Diagnostics | 已吸收 | Diagnostics 已由单次 FailureReport 取代；不脱敏是当前明确决定 |
| CR-05 核心领域政策 | 未解决 | Package 机制已具备，但 Corpse、Survival、Equipment 等政策仍在核心 |
| CR-06 测试偏局部 | 部分遗留 | 新增了跨 Executor/Settlement 的契约测试，旧测试仍固定大量旧语义 |
| CR-07 Event/Interaction 混杂 | 部分遗留 | Recipe/Reaction interaction 与 Agent view 已分离；稳定可见性和 interaction ID 仍需收尾 |
| CR-08 缺少 Action | 未解决 | 只有可选的 `action_id` 字段，没有 Action 生命周期或持久化对象 |
| CR-09 Effect 事件契约 | 部分遗留 | 通用 EffectRecord 已解决最低追踪要求；扩展事件 schema 和 lint 尚未定义 |
| CR-10 Reaction 叙事 | 部分吸收 | `narrative_success` 已生成一条 Reaction interaction；动态上下文和 Action 关联仍未完成 |
| CR-11 动态文本双契约 | 未解决 | `KERN.dynamic_text` 与 Recipe 的 `{actor}/{target}/{reason}` 仍并存 |
| CR-12 Bundle 追踪 | 部分吸收 | 运行时父子追踪已存在；作者语义和显式 Bundle 规范仍未收敛 |
| CR-13 Task interaction 特例 | 部分遗留 | Travel 硬编码已移除；Task lifecycle Bundle 的显式 interaction 约定仍需补齐 |

## 4. 已被新架构吸收的历史问题

### 4.1 CR-01 的日志提前写入

历史问题是 Workflow 在执行前直接写入 success interaction，Bundle 回滚后仍留下成功事实。

当前路径是：

```text
command
-> InteractionEngine 编译
-> 插入 RecordInteraction Effect
-> Bundle 执行
-> 成功后由 Settlement 发布 EffectRecord
```

因此，失败 Bundle 不会留下成功 interaction，也不会触发 Reaction。原问题的核心事务缺陷已经消失。

仍需单独决定：

1. `ActionRejected` 是否产生显式 `attempt` 记录；
2. 一个 decision 的多个 command 是每个 command 一个 Bundle，还是整个 decision 一个 Bundle；
3. `AgentControlTick` 是否长期保留为普通编排 Effect。

### 4.2 CR-03 的复杂错误处置矩阵

当前产品决定把所有错误视为致命错误。运行时策略已经收敛为：

```text
KernFailure ->（若存在）包含它的 Bundle 回滚 -> Runtime terminal -> failure.json
```

`ActionRejected` 是正常的决策结果，不属于错误路径。原文档中关于 `recoverable`、degrade-to-noop 和多套错误处置矩阵的讨论应归档，不再作为独立恢复任务。

### 4.3 CR-04 的 Diagnostics

旧 Diagnostics、多个连续错误日志和 `diagnostic_recorder` service 已移除。当前只保留：

- 运行内存中的当前异常及其 cause chain；
- 一份独立的 `failure.json`；
- LLM 失败时附带的原始 request/response evidence。

FailureReport 不属于 `WorldState`，也不参与世界事务。原文档中“FailureReport 需要自行定义 category”以及“必须脱敏”的内容已过时。

### 4.4 CR-09、CR-10 和 CR-12 的最低运行时能力

EffectRecord 已提供默认执行路径的通用外壳；空输出自动获得 `EffectExecuted`。Executor 在 Bundle 执行中生成运行时 ID，并记录父 Bundle 关系。Recipe 和 Reaction 在存在 `narrative_success` 时分别自动插入一条 interaction Effect；没有 narrative 时不写 interaction。扩展作者可以自由定义业务 facts，但当前仍存在 `_effect_record=True` 直接透传和直接 `WorldExecutor.execute` 缺少 Bundle 追踪字段的收尾问题。

这使“每个 Effect 是否可追踪”和“嵌套事件是否必须复制完整 Bundle 树”不再是阻断问题。

## 5. 当前仍需处理的问题

### P-01 错误身份收尾（来源：CR-02）

当前 `KernFailure.to_dict()` 已包含：

```text
code, category, disposition, retryable, message,
origin, phase, cause, context
```

剩余工作：

- 为仍使用默认 `EXECUTOR_FAILURE` 的 Handler 分配稳定 code；
- 明确普通 Python 异常的 category 归属；
- 用契约扫描或测试保证所有 Handler 的错误都能生成完整 Failure schema。

这属于错误模型的质量收尾，不再需要重新设计 FailureReport。

验收：扫描所有 Handler 的失败路径，每个 Failure 都有稳定 `code`，并能序列化完整 schema。

### P-02 Interaction、Event 与 Agent 记忆边界（来源：CR-07）

当前 World 已保存完整 `event_log` 和 `interaction_log`。Agent workflow view 不再提供 `event_delta`，memory policy 也只消费 interaction delta；可见性规则和 interaction 的稳定身份仍需继续收敛。

剩余工作：

- 明确哪些 interaction 对 Agent 可见；
- 为 Reaction 的流程控制记录和可感知记录建立明确区分；
- 用稳定 interaction ID 替代 `UpdateInteractionDetails` 对“最后一条记录”的依赖。

验收：Agent 记忆输入不再依靠 Event 类型黑名单补救；回滚、流程控制和可感知 interaction 有独立测试。

### P-03 领域政策隔离（来源：CR-05）

Package 组合和运行时 Catalog 已经具备，社交平台实现也已从核心移除。以下内容仍需判断是否迁入 capability package：

- `KillEntity` 默认生成 `Corpse`、生成中文尸体名并搬运遗物；
- `CorpseSightedRule`、`LowNutritionRule`；
- `CreatureComponent`、`EdibleComponent`、`EquipmentComponent`；
- 交易、价值和生存相关的 Effect/Component。

目标是保留通用机制（Create、Destroy、Move、Modify、Emit），将领域政策放入显式选定的 Package。

验收：未选择 capability package 时，相关 Component、Effect 和政策规则不进入 Runtime Catalog；选择后 Camping smoke 保持通过。

### P-04 运行时依赖边界（来源：I-07）

`WorldState.services["execute"]` 仍是 Workflow、Effect Handler 和嵌套 Bundle 的运行入口。它目前是受控的既有 seam，但仍然是隐式接口。

后续需要把 Workflow 和嵌套执行依赖收敛到小而明确的 Runtime Interface，并保持现有 `WorldState.services` 兼容行为，避免继续增加任意字符串键。

验收：Workflow 和嵌套执行只依赖显式 Runtime Interface；不新增未登记的 `WorldState.services` key。

### P-05 契约测试迁移（来源：CR-06）

新契约测试已经覆盖：

- 失败 Bundle 回滚；
- EffectRecord 输入；
- Reaction 提交后触发；
- interaction Effect 的事务性；
- 单次 FailureReport。

旧测试仍有一批 failure/error，主要期待旧的错误返回值、裸业务 Event 或 LLM 自动 noop。计数可能受 LLM/gateway 测试顺序影响，因此不能把一次全量计数当作稳定指标；它们不能作为当前契约的验收标准，后续应删除或改写，而不是增加兼容层。

验收：契约测试通过真实 Runtime seam 验证事务、Settlement、FailureReport 和越权写入边界；旧语义断言被删除或改写。

### P-06 Decision 结果分类（来源：CR-01、CR-03）

`_commands_to_operations()` 当前把 InteractionEngine 的 `rejected` 和 `failed` 都映射为 `ActionRejected`。在“所有错误致命”的产品决定下，合法但当前不可执行的动作可以返回 rejection；Recipe contract、Binder 或运行时失败必须保留为 `KernFailure`。

验收：每个 InteractionEngine 非 success 结果都有明确的 rejection 或 fatal 映射，错误不会被降级成正常 rejection；rejection 若写入日志必须标记为 attempt。

### P-07 FailureReport 输出隔离（来源：CR-04）

`FailureReportWriter` 对单个 Writer 只写一次，但默认 `checkpoint_dir` 可能被多个 Runtime 共享，导致不同运行的 `failure.json` 互相覆盖。当前“每个 Runtime 一份”依赖调用方为每次运行提供独立输出目录。

验收：同一输出根目录启动多个 Runtime 时，每次运行的报告都可独立定位；报告写入失败仍不改变世界结果。

## 6. 尚未决定的设计问题

### D-01 Action 模型（来源：CR-08）

需要决定 Action 是：

- 仅存在于执行上下文中的稳定 ID；还是
- 需要进入 checkpoint/archive 的正式持久化对象。

还需要定义 Action 的状态集合、Recipe rejection 是否创建 Action，以及跨 tick Task 是否保持同一个 Action。

验收：同一 Action 的根 Bundle、EffectRecord、interaction 和跨 tick 生命周期可由稳定 ID 关联，并明确 checkpoint/archive 行为。

### D-02 Reaction 叙事（来源：CR-10）

Reaction 的可选 `narrative_success` 语义已经接入：

- 有 narrative 的 Reaction 产生一条 Reaction interaction；
- 没有 narrative 的 Reaction 只承担流程控制；
- Reaction 失败仍然抛出致命 `KernFailure`。

仍需规定 actor、target、location 和 trigger event 如何进入统一动态文本上下文，并在未来与 Action ID 关联。

验收：Reaction 有 narrative 时生成一次 Action 级 interaction；无 narrative 时不进入 Agent 经历；Reaction 失败进入统一 Failure 路径。

### D-03 动态文本统一（来源：CR-11）

Recipe、Reaction、Task interaction 和明确支持文本字段应使用同一个渲染模块。需要统一：

- `{actor}/{target}/{reason}` 与 `{self.*}/{target.*}/{event.*}/{param:*}` 的语法；
- 执行前渲染和提交后落盘之间的快照规则；
- 对已被 Destroy 的实体仍可用的名称快照；
- lint 可以验证的引用路径。

验收：Recipe、Reaction 和 Task 文本使用同一渲染器，文本只渲染一次，非法引用在 lint 或运行前失败。

### D-04 Task interaction 生命周期（来源：CR-13）

Task 已有 start、tick、cleanup、completion Bundle。Travel 硬编码已移除，数据作者可以在需要的生命周期 Bundle 中显式放置 `RecordInteraction`。

需要另外决定开始、完成、中断、恢复是否分别产生 interaction，以及一个跨 tick Task 是否对应一个 Action。

验收：Travel 不再依赖硬编码完成分支；任务 interaction 只由生命周期 Bundle 中显式的 interaction Effect 产生。

### D-05 扩展 Effect 与 Bundle 作者契约（来源：CR-09、CR-12）

运行时最低契约已经确定：Effect 成功后必须生成通用 EffectRecord。仍需决定：

- 扩展包是否声明业务 fact schema；
- 一个 Effect 的多个 fact 是否需要显式顺序或类型约束；
- 没有显式 Bundle 的 Effect 是否统一包装成单 Effect Bundle；
- `_effect_record=True` 是否禁止扩展绕过通用 EffectRecord 外壳；
- 命名 Bundle 的复用 ID 与运行时 Bundle ID 如何区分；
- package lint 检查哪些扩展事件约束。

验收：自定义 Effect 的 facts、空输出、Bundle 父子关系和运行时 ID 都能通过 lint 或契约测试验证。

### D-06 多 command decision 原子性（来源：CR-01）

当前代码把每个编译后的 operation 交给独立 Bundle 执行。这是实现现状，不代表最终产品语义已经确认。

需要在以下两种语义中明确选择：

1. 每条 command 独立提交，前一条成功不会被后一条回滚；
2. 整个 decision 作为一个 Bundle，任一 command 失败则整体回滚。

验收：选择一种语义后，前一条 command 是否保留、interaction 结果和 Reaction 输入都有跨模块测试覆盖。

## 7. 已过时或应归档的讨论

以下内容不应继续出现在当前问题清单中：

- 多条 Diagnostics 连续错误模型；
- `ExecutorError` 作为普通返回值的兼容设计；
- LLM ungroundable 自动降级为合法 noop；
- FailureReport 的独立 category 词表；
- 为开发者错误报告强制脱敏；
- 依赖 Event 黑名单承担 Agent 记忆边界的实现已删除；当前只保留 interaction 可见性规则的收尾工作。

这些内容可以保留在 git 历史和审查记录中，当前计划只保留它们对新架构的迁移结论。

## 8. 建议实施顺序

1. 完成 P-01 错误 code 和 schema 扫描，锁定 Failure 的机器身份。
2. 完成 P-02 interaction、Reaction 和 Agent 记忆边界。
3. 完成 P-06 结果分类，并决定 D-06 多 command 原子性。
4. 解决 P-07 报告输出隔离，再补充跨 Runtime FailureReport 测试。
5. 决定 D-01 Action 身份，再处理 Reaction narrative 和 Task lifecycle。
6. 统一 D-03 动态文本，再迁移 D-04 Task interaction 特例。
7. 依据 P-03 清单迁移领域政策到 capability package。
8. 最后清理旧测试并补齐 D-05 扩展 lint 契约。

## 9. 当前验证命令

```powershell
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.package.smoke.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.package.smoke.json
```

上述命令和 `tests.test_failure_and_effect_records` 是当前契约门禁。全量旧测试仅作为迁移观测：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

当前验证记录：

- `tests.test_failure_and_effect_records`：11 项通过；
- `compileall`：通过；
- Camping package lint：0 error、0 warning；
- Camping smoke：退出码 0；
- 最近一次全量旧测试记录为 156 项、3 failures、16 errors；计数可能受 LLM/gateway 测试顺序影响。已知失败主要固定了旧错误返回值、裸业务 Event 或旧 LLM 降级语义，外部/LLM 波动项需单独诊断。

每个后续问题完成时必须记录：实际修改、跨模块验证、剩余风险、是否改变 checkpoint/archive schema，以及下一项工作的前置条件。
