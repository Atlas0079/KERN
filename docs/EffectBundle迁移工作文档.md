# EffectBundle 迁移工作文档

## 目标
- 显式定义 `EffectBundle`，统一承载一组顺序执行的 effects。
- 清理项目中的隐式 effect 串，不再保留 `outputs`、`effects`、`completion_effects` 这类并列概念。
- 为后续 `ApplyToQuery`、`ResolveDropTable`、动态文本等容器型能力提供统一执行基础。
- 将运行时调度原子从单个 `effect` 切换为 `bundle`，统一 `Recipe / Reaction / Task / Workflow` 的执行入口。
- 让 `react_per_effect` 成为 `bundle` 的自然调度属性，而不是 `InvokeBundle` 的特殊分支逻辑。

## 本次迁移范围
- `Recipe`：`bundle`
- `Reaction`：`bundle`
- `Task`：`tick_bundle`、`completion_bundle`
- 组件内嵌 bundle：先覆盖 `EdibleComponent.on_consume_bundle`
- Executor：新增统一 bundle 执行入口
- 数据/快照：读写新结构，不保留旧字段兼容
- Manager / TriggerSystem / Workflow Runtime：统一改为传递 `bundle + context`
- `InvokeBundle`：从主调度入口收缩为运行时 bundle 引用桥接能力

## 新的核心概念
- `EffectSpec`：单个 effect 的声明
- `EffectBundle`：`{"effects": [EffectSpec, ...], "react_per_effect"?: bool}`
- `ExecutionContext`：bundle 执行时使用的上下文绑定
- 调度层原子：`bundle`
- 执行层原子：`effect`

## 迁移原则
- 不引入 bundle 局部变量
- 不引入脚本语言能力
- 不做旧字段兼容读取
- 容器型逻辑统一委托给 bundle 执行器
- `WorldManager` 负责 bundle 调度与 reaction 递归；`Executor` 只负责单个 effect 的绑定与写世界
- 直接执行 bundle 的内部调用尽量经 `ws.services["execute"]` 返回到 Manager，不绕过 reaction 调度

## 已确认的旧入口
- `recipe.outputs`
- `reaction.effects`
- `task.tick_effects`
- `task.completion_effects`
- `dynamic_outputs_from_component`
- `EdibleComponent.effects_on_consume`

## 当前实施步骤
1. 新增 `EffectBundle` 模型与执行器
2. 改造 `Recipe / Reaction / Task` 运行时代码
3. 改造世界构建与 checkpoint 序列化
4. 迁移 `Data/` 下相关 JSON
5. 将运行时调度入口从 `effect` 切换为 `bundle`
6. 将 `ExecuteBundle` 重命名为 `InvokeBundle`，并收缩其职责，只保留运行时 bundle 调用/引用桥接
7. 运行编译和诊断检查

## 当前需求
- `ws.services["execute"]` 的签名统一为 `(bundle, context)`，不再接收单个 effect。
- `TriggerSystem.build_reaction_effects()` 返回 `bundle + context`，不再包装 `InvokeBundle(bundle=...)`。
- Workflow Runtime 的 `operations` 统一改为 `bundle + context`。
- `WorkerTick / FinishTask / MemoryPatch / AbortSimulation` 等运行时内部调用统一改为传递 bundle。
- `InvokeBundle` 保留，但不再作为主调度适配器；它主要负责执行显式内联 bundle，或从组件属性读取 bundle 后再交回统一 bundle 调度入口。
- `Task.completion_bundle` 和 `Task.tick_bundle` 需要经过统一 bundle 调度入口，保证 `react_per_effect` 语义一致。

## 当前进度
- 已完成：`Query` / `Condition` 解耦，形成通用查询层
- 已完成：`EffectBundle` 显式化，`Recipe / Reaction / Task / EdibleComponent` 读写统一到 bundle
- 已完成：`react_per_effect` 开关，默认关闭，显式 `true` 时逐 effect 触发 Reaction
- 已完成：`TaskHostComponent.tasks` 在 snapshot/checkpoint 恢复时不再被 raw dict 污染
- 已完成：`WorldManager` 调度入口切换为 `bundle`
- 已完成：TriggerSystem / Workflow Runtime / WorkerTick / FinishTask 内部调用改为传递 bundle
- 已完成：`ExecuteBundle` 已重命名为 `InvokeBundle`，并优先将 bundle 交回统一 bundle 调度入口执行
- 已确认：显式内联 bundle 能力暂时保留，不在本轮迁移中继续收缩
- 进行中：清理仍然直接调用 `executor.execute_bundle()` 的少量内部路径，统一其调度语义
