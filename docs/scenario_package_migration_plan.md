# KERN Package 组合迁移计划

> 状态：实施中。阶段 0–3 已完成；下一项为阶段 4（能力包 Effect 发现）。

## 目标

一次 KERN 运行由多个被 config 明确选择的 Package 组成。每个 Package 都是用户信任
的输入：选择它即表示允许执行它声明的 Python 扩展。Package 可以只提供组件、codec
和 effect；一次运行必须指定且只能指定一个提供初始世界的世界包。

```text
Runtime
├─ KERN core 能力
├─ 能力包：Weather
├─ 能力包：Crafting
└─ 世界包：Camping（World、Entities、Recipes、Reactions）
```

能力只注册到本次 Runtime 的 Catalog。另一次 Runtime 会重新装配自己的 Catalog，
因此选择了 Weather 的 Camping 不会让 Farm 自动获得天气能力。

## 已完成的基础

阶段 0–2 已在 `laptop` 分支落地：

- `34e8d55 Introduce runtime-scoped effect catalog`
- `840b656 Centralize component construction and checkpoint codecs`

每次 Runtime 都有独立的 `EffectCatalog` 和 `ComponentCatalog`。EffectCatalog 被 lint
和 executor 共用；ComponentCatalog 被 lint、world build、restore、executor 和 archive
共用。二者均在运行前冻结。

组件通过 codec 在模板 JSON、内存对象和 checkpoint JSON 之间转换；TaskHost codec 会
保存任务及其生命周期 bundle。checkpoint 保存 effect 数据，不保存 Python handler
代码或 Catalog。

## 固定决策

- KERN 保留小而稳定的 core Effect 和组件；Bundle 保持为有限、可序列化的 effect
  列表，不发展为脚本语言。
- 组件保存状态；世界行为由 Effect 或 System 承担。
- config 中选择 Package 即代表用户信任该 Package 及其代码。没有单独的
  `allow_scenario_code` 开关；第一版也不尝试构造 Python 沙箱。
- loader 只加载 config 列出的 Package 和 Package 固定入口列出的模块；不扫描磁盘
  上的其它目录或 Python 文件。
- 一个 Package 根目录包含 `kern-package.json`。有代码扩展时，固定入口为根目录
  `extensions.py`；入口只声明模块，不保存 Catalog，也不直接执行仿真。
- loader 只从入口声明的模块中发现带明确标记的 Effect 和组件定义。它们写入当前
  Runtime 的本地 Catalog；import 代码不得修改模块级全局注册表。
- config 必须恰好指定一个 `world: true` 的 Package。该 Package 的 manifest 必须声明
  `provides_world: true` 并提供 `Data/World.json`。第一版中，只有世界包提供启动数据；
  能力包只提供代码能力。
- Package 按 config 顺序处理。ID、Effect ID 或组件 ID 的冲突一律报错，不采用后者覆盖
  前者的隐式规则。
- legacy `Data/` 布局和 runtime config 在迁移期继续可用，由 adapter 视为一个无扩展的
  旧式世界包。

## config 与 Package 格式

新的 config 使用顶层 `packages` 数组，`env` 保留现有运行时参数：

```json
{
  "packages": [
    { "path": "Packages/Weather" },
    { "path": "Packages/Crafting" },
    { "path": "Scenarios/Camping", "world": true }
  ],
  "env": {
    "USE_LLM": "0"
  }
}
```

最小能力包 manifest：

```json
{
  "package_id": "weather",
  "version": "1.0.0",
  "extensions": "extensions.py",
  "provides_world": false
}
```

最小世界包 manifest：

```json
{
  "package_id": "camping",
  "version": "1.0.0",
  "provides_world": true,
  "data": {
    "world": "Data/World.json",
    "entities": ["Data/Entities"],
    "recipes": ["Data/Recipes.json"],
    "reactions": ["Data/Reactions.json"],
    "bundles": ["Data/Bundles.json"]
  }
}
```

`extensions.py` 只声明可被发现的相对模块：

```python
EFFECT_MODULES = ("effects.weather",)
COMPONENT_MODULES = ("components.weather",)
```

loader 依声明顺序导入模块，并只收集带 `@package_effect` 或
`@package_component` 标记的定义。组件和 codec 先注册；Effect 后注册；随后冻结两个
Catalog，再读取世界包数据和 lint。

## 后续实施顺序

### 阶段 3：Package config、manifest 与世界包（已完成）

已新增 `KERN.package` 的 manifest、package loader 和 legacy adapter。loader 复用现有
`load_data_bundle(...)`，不复制另一套数据读取逻辑。`LoadedPackages` 保存已解析的 Package
清单、唯一 world package 和 world data bundle；Runtime 与 lint 使用同一个加载入口。

`KernRuntime.from_config(...)` 识别顶层 `packages`。它验证每个路径都在项目根目录内、
Package ID 不重复，并验证恰好一个 `world: true` 条目与 manifest 一致。缺少新字段时，
legacy adapter 继续读取现有 `WORLD_JSON`、`RECIPES_JSONS` 等字段。

`KernRuntime.from_loaded_packages(...)` 可复用已验证的组合进行 Runtime 装配。阶段 3 不执行
`extensions.py`；能力包可以参与组合解析，Catalog 扩展和 Package 身份 hash 留给阶段 4–6。

验收：独立世界包可加载；能力包可被解析但在本阶段不执行 Python；路径逃逸、重复 ID、
零或多个世界包、manifest/data 不一致均有明确报错；旧入口产生等价 WorldState。以上由
`tests/test_package_loading.py` 覆盖。

### 阶段 4：能力包 Effect 发现

对每个 config 选择且声明 `extensions.py` 的 Package，loader 执行入口并读取
`EFFECT_MODULES`。它按相对模块路径导入、收集 `@package_effect` 定义，并注册到 core
EffectCatalog 的可变 clone。Effect ID 必须具备 Package 命名空间，不能覆盖 core 或其它
Package 的 ID。

lint 与 executor 使用同一个扩展后的 Catalog。所选 Package 的入口缺失、模块路径非法、
导入失败、标记错误或 ID 冲突均立即失败。

验收：选中 Weather 后其 Effect 仅在该 Runtime 可见；未选中 Weather 的 Runtime 无法
引用其 Effect；场景 Effect 在单 effect 和 bundle 事务中与 core Effect 有相同语义。

### 阶段 5：能力包组件和 codec 发现

先读取所有选中 Package 的 `COMPONENT_MODULES`，发现带 `@package_component` 标记的组件，
再加载 Effect。组件只能是纯数据 dataclass；默认采用 `DataclassCodec`，特殊转换才允许
Package 提供 codec。ComponentCatalog 在 build 和 restore 前冻结并被两者共用。

验收：自定义组件能由世界包模板构造、被 query/effect 读取或修改，并在 checkpoint 后
保留类型和值；未选中能力包时同名组件不会静默得到该类型；不同 Runtime 的 Catalog
隔离成立。

### 阶段 6：archive 身份与可复现性

snapshot meta 保存完整 Package 组合，而非单个场景身份：

```json
{
  "packages": [
    { "package_id": "weather", "version": "1.0.0", "content_hash": "..." },
    { "package_id": "camping", "version": "1.0.0", "content_hash": "...", "world": true }
  ],
  "effect_ids": ["weather:ChangeWeather"],
  "component_ids": ["weather:WeatherComponent"]
}
```

hash 覆盖 manifest、被引用 JSON 和已加载 Python 源文件。恢复时先按 config/metadata
加载相同 Package 组合、注册本地 Catalog、验证身份和 hash，再解码 checkpoint。任何
缺失 Package、版本、能力或 hash 不一致默认拒绝；无扩展的 legacy checkpoint 保持现有
恢复路径并标记为 legacy。

### 阶段 7：Camping 真实迁移

将 Camping 迁为世界包，并选择一个小的、实际有用的能力包验证组合机制。比较旧入口和
新 Package config 的初始世界状态、固定 tick 的关键事件与 checkpoint round-trip。稳定
后再决定旧 `Data/Camping` 的弃用时间。

验收：Package config lint、Camping no-LLM smoke、checkpoint round-trip 通过；旧 config
在明确兼容期内继续工作。

## 测试与兼容约束

每阶段独立提交、独立验证。至少运行：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.example.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.smoke.json
```

迁移过程中不顺手修改任务生命周期、Bundle 控制流、LLM workflow、runtime context 或
场景数值。发现的无关问题应单独记录并用最小测试固定现状。
