# KERN 内核待决事项

最近按实现复核：2026-07-25。

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

验收：未选择 capability Package 时，领域 definition 不进入 runtime catalog；选择后 Camping
行为和恢复兼容性保持清晰。

## 4. Typed runtime context

`WorldState.services` 仍承载 executor、workflow、provider 和 external runtime 的运行依赖。
需要设计小型显式 Runtime Interface，并给现有字符串键保留清楚的兼容边界。在完成专项
设计前不增加新 service key。

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

