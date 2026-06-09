# Bundle 结构查询与编辑辅助方案

> 当前状态：暂缓实现。
>
> 本文档保留为后续复杂场景维护工具的设计参考。当前阶段只实现运行时所需的
> `RandomBundle` 能力；Bundle Inspection CLI、MCP/Skill 与编辑器可视化暂不进入实现范围。

## 背景

随着 `EffectBundle` 成为调度层原子，场景数据会逐渐出现更复杂的嵌套结构，例如：

- `RandomBundle` 的随机分支
- `InvokeBundle` 引用组件或内联 bundle
- `ApplyToQuery` 对查询结果批量执行 bundle
- Task 的 `start_bundle` / `tick_bundle` / `completion_bundle` / `cleanup_bundle`
- Reaction 中继续触发新的 bundle

这些结构仍然符合当前 DSL 边界：扁平、可序列化、可审计，不引入局部变量、循环或脚本执行栈。

但当 bundle 嵌套三四层后，单纯阅读 JSON 会变得困难：

- 人类很难直观看到某个分支之后还会执行什么。
- LLM 如果只拿到局部文本，无法完整理解后续分支。
- 如果把全部 Data 都塞进 LLM 上下文，会浪费上下文并降低稳定性。

因此需要一套面向人类和 LLM 的 bundle inspection 能力。

## 核心目标

### 1. 人类编辑者需要结构化视图

未来可以开发一个编辑器工具，用树状图或节点图展示 bundle 结构：

- 展开 / 折叠嵌套 bundle
- 查看 `RandomBundle` 的各个 entry
- 查看每个 entry 的权重、标签和后续 bundle
- 跳转到 bundle 来源文件与 JSON 路径
- 标记某个分支最终会产生哪些关键事件或资源变化

这个编辑器主要解决“人类直观理解和维护复杂数据”的问题。

### 2. LLM 编写数据时需要按需查询

LLM 不应该依赖一次性读取所有场景数据来理解结构。

更合理的方式是提供一个可调用的查询服务，让 LLM 可以按需询问：

- 某个 recipe 的 bundle 展开后是什么？
- 某个 `RandomBundle` 有哪些分支？
- 某个分支继续往下会执行哪些 effect？
- 某个 bundle 最终可能产生哪些事件？
- 某个资源模板在哪些 bundle 分支中被创建？
- 某个 effect 会被哪些 recipe / reaction / task 引用？

这个服务可以是 MCP 服务器，也可以是项目专用 skill，也可以先从普通 CLI 工具开始。

## 推荐方向：Bundle Inspection Service

建议将该能力抽象为一个独立的 Bundle Inspection Service。

它不参与运行时仿真，不改变世界状态，只做静态数据解析和结构查询。

### 服务职责

- 加载 Data 下的 world / recipes / reactions / entities，以及 world/entity 中的 task 快照。
- 识别所有 bundle 来源。
- 给每个 bundle 建立稳定引用路径。
- 支持展开嵌套 bundle。
- 支持限制展开深度。
- 支持按路径查询局部分支。
- 支持生成 LLM 友好的文本摘要。
- 支持生成编辑器友好的结构化 JSON。

### 非职责

- 不执行 effect。
- 不做随机实际抽样。
- 不修改场景数据。
- 不承担运行时调度。
- 不引入新的 DSL 语义。

## Bundle 引用路径

为了让人类、LLM、编辑器和日志能指向同一个结构，需要给 bundle 建立统一路径格式。

建议路径示例：

```text
recipe:FishAtPond.bundle
recipe:MineOre.progression.tick_bundle
reaction:market_wood_abundant.bundle
entity:processing_station.TaskHostComponent.tasks.process_ore.completion_bundle
random_bundle:arena_fishing_basic.entry.good_fish.bundle
```

其中 recipe 的成功完成效果来自 `recipe:<id>.bundle`；`completion_bundle`
是 Task 固化后的字段，主要出现在 world/entity 快照中的
`TaskHostComponent.tasks.<task_id>.completion_bundle`。

对于内联嵌套结构，可以继续追加路径：

```text
recipe:FishAtPond.bundle.effects[0]
recipe:FishAtPond.bundle.effects[0].entries[1].bundle
recipe:FishAtPond.bundle.effects[0].entries[1].bundle.effects[0]
```

如果 `RandomBundle` 有 `table_id` 和 entry `id`，优先使用语义路径：

```text
random_bundle:arena_fishing_basic.entry.good_fish.bundle
```

这要求后续编写 `RandomBundle` 时尽量提供：

- `table_id`
- `entry.id`
- `entry.label`

## LLM 查询接口草案

### 1. 查询 bundle 概览

输入：

```json
{
  "op": "bundle_summary",
  "path": "recipe:FishAtPond.bundle",
  "max_depth": 2
}
```

输出：

```json
{
  "path": "recipe:FishAtPond.bundle",
  "effect_count": 1,
  "summary": [
    {
      "path": "recipe:FishAtPond.bundle.effects[0]",
      "effect": "RandomBundle",
      "table_id": "arena_fishing_basic",
      "entries": [
        {"id": "trash_fish", "label": "钓到垃圾鱼", "weight": 70},
        {"id": "good_fish", "label": "钓到好鱼", "weight": 30}
      ]
    }
  ]
}
```

### 2. 展开随机分支

输入：

```json
{
  "op": "random_bundle_entries",
  "table_id": "arena_fishing_basic"
}
```

输出：

```json
{
  "table_id": "arena_fishing_basic",
  "entries": [
    {
      "id": "trash_fish",
      "label": "钓到垃圾鱼",
      "weight": 70,
      "bundle_path": "random_bundle:arena_fishing_basic.entry.trash_fish.bundle"
    },
    {
      "id": "good_fish",
      "label": "钓到好鱼",
      "weight": 30,
      "bundle_path": "random_bundle:arena_fishing_basic.entry.good_fish.bundle"
    }
  ]
}
```

### 3. 查询某个分支的完整展开

输入：

```json
{
  "op": "expand_bundle",
  "path": "random_bundle:arena_fishing_basic.entry.good_fish.bundle",
  "max_depth": 4
}
```

输出应包含：

- 当前 bundle 的 effect 列表
- 子 bundle 的引用路径
- 遇到 `RandomBundle` 时列出 entries，但不实际随机
- 遇到 `InvokeBundle` 时解析引用目标
- 遇到 `ApplyToQuery` 时显示 query 与 child bundle

### 4. 查询资源或事件来源

输入：

```json
{
  "op": "find_effects",
  "effect": "CreateEntity",
  "template": "GoodFish"
}
```

输出：

```json
{
  "matches": [
    {
      "path": "random_bundle:arena_fishing_basic.entry.good_fish.bundle.effects[0]",
      "owner": "recipe:FishAtPond.bundle",
      "effect": "CreateEntity",
      "template": "GoodFish"
    }
  ]
}
```

## LLM 友好摘要格式

除结构化 JSON 外，服务还应能生成短文本摘要，供 LLM 快速阅读：

```text
Bundle recipe:FishAtPond.bundle
- effect[0] RandomBundle table=arena_fishing_basic
  - entry trash_fish weight=70 label=钓到垃圾鱼 -> creates TrashFish into self container
  - entry good_fish weight=30 label=钓到好鱼 -> creates GoodFish into self container
```

这种摘要不替代原始 JSON，只用于帮助 LLM 在有限上下文中理解结构。

## 与运行时事件的关系

运行时的 `RandomBundle` 应产生类似事件：

```json
{
  "type": "RandomBundleResolved",
  "table_id": "arena_fishing_basic",
  "entry_id": "good_fish",
  "entry_label": "钓到好鱼",
  "entry_index": 1,
  "weight": 30.0,
  "total_weight": 100.0,
  "roll": 83.27,
  "bundle_effect_count": 1
}
```

Bundle Inspection Service 可以用 `table_id` 与 `entry_id` 将运行时事件映射回静态数据路径：

```text
random_bundle:arena_fishing_basic.entry.good_fish.bundle
```

这样 viewer、日志、LLM 调试工具可以从运行时事件反查“这个随机结果对应的配置分支”。

## 实现阶段建议

### 第一阶段：CLI 工具

当前仓库尚未包含 `tools/bundle_inspect.py`。后续可先实现一个只读 CLI，例如：

```powershell
py tools\bundle_inspect.py --config runtime_config.arena.json summary recipe:FishAtPond.bundle
py tools\bundle_inspect.py --config runtime_config.arena.json random arena_fishing_basic
py tools\bundle_inspect.py --config runtime_config.arena.json expand random_bundle:arena_fishing_basic.entry.good_fish.bundle --max-depth 4
```

优点：实现简单，容易接入测试，也可以被 LLM 通过命令调用。

### 第二阶段：MCP / Skill

当 CLI 稳定后，可以包装成 MCP 服务器或专用 skill。

推荐提供工具：

- `bundle_summary(path, max_depth)`
- `expand_bundle(path, max_depth)`
- `random_bundle_entries(table_id)`
- `find_effects(filters)`
- `find_bundle_refs(path_or_id)`

### 第三阶段：编辑器可视化

编辑器可以复用同一套 inspection 输出：

- 左侧展示 bundle tree
- 中间展示当前分支 JSON
- 右侧展示可能事件 / 资源变化摘要
- 支持点击运行时事件跳转到静态分支

## 架构边界

该方案必须遵守以下边界：

- Inspection 是只读工具，不参与仿真运行。
- 不为了 inspection 改变运行时语义。
- 不在 JSON DSL 中引入脚本语言能力。
- 不把复杂推理塞进 Data；复杂理解由工具层完成。
- 优先提供可序列化、可查询、可审计的结构。

## 当前结论

复杂 bundle 不应该靠人类或 LLM 手动在 JSON 中翻找。

正确方向是：

1. Data 继续保持扁平、可序列化、可审计。
2. Runtime 继续只负责执行和记录事件。
3. Human Editor 用结构化视图理解分支。
4. LLM 通过 Bundle Inspection Service 按需查询分支，不一次性吞全部上下文。

这可以让后续 `RandomBundle`、竞技场场景和更复杂的数据化场景保持可维护。
