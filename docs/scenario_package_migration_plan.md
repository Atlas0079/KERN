# ScenarioPackage 迁移计划

> 状态：实施中。阶段 0–2 已完成；下一项为阶段 3（数据型 ScenarioPackage）。

## 目标

让一个场景可以作为独立目录加载。它可以是只含 JSON 的数据场景，也可以在用户
显式授权后携带受信任 Python 扩展。场景扩展只能作用于自己的 Runtime，不能污染
其他场景。

完成后的调用边界应保持很小：调用方提供场景路径和代码授权；ScenarioPackage
内部处理 manifest、数据、能力注册、验证、Catalog 隔离和 archive 身份校验。

## 已完成的基础

阶段 0–2 已在 `laptop` 分支落地：

- `34e8d55 Introduce runtime-scoped effect catalog`
- `840b656 Centralize component construction and checkpoint codecs`

当前 Runtime 为每次运行创建独立的 `EffectCatalog` 和 `ComponentCatalog`。同一
Catalog 被 lint、world build、checkpoint restore、executor 和 archive 共同使用，
并在运行前冻结。

组件通过 codec 在模板 JSON、内存对象和 checkpoint JSON 之间转换；TaskHost codec
会保存任务及其生命周期 bundle。EffectCatalog 保存可执行能力定义；checkpoint
只保存 effect 数据，不保存 Python handler 代码。

## 固定决策

- KERN 保留小而稳定的 core Effect 和组件。
- Bundle 继续是有限的、可序列化的 effect 列表，不发展为脚本语言。
- 组件保存状态；世界行为由 Effect 或 System 承担。
- 场景代码属于受信任代码，拥有与 KERN 进程相同的权限。第一版不构造 Python
  沙箱。
- 代码加载默认关闭；只允许 manifest 约定目录内、通过路径校验的文件，并要求
  CLI/SDK 显式授权。
- 代码场景的固定装配入口是包根目录 `extensions.py`。它只声明可发现的扩展模块，
  不保存 Catalog，也不直接执行仿真。
- 内核只从 `extensions.py` 声明的模块中发现带明确标记的 Effect 和组件定义，并将它们
  注册到当前 Runtime 的本地 Catalog；禁止 import 时修改模块级全局注册表。
- 运行中的 Catalog 不可变。场景扩展在 build/restore 前注册，随后冻结。
- legacy `Data/` 布局和 runtime config 在迁移期继续可用。

## 目标包结构

```text
Scenarios/
└─ Camping/
   ├─ scenario.json
   ├─ Data/
   │  ├─ World.json
   │  ├─ Entities/
   │  ├─ Recipes.json
   │  ├─ Reactions.json
   │  └─ Bundles.json
   ├─ extensions.py               # 仅代码场景使用的固定入口
   ├─ effects/
   │  ├─ campfire.py
   │  └─ weather.py
   └─ components/
      └─ weather.py
```

manifest 负责说明场景身份、版本、数据文件路径和是否包含扩展代码。runtime config
负责选择场景、运行时参数、LLM/provider 和 checkpoint 路径；它不重新声明场景内部
文件清单或扩展模块。

`extensions.py` 的第一版契约只声明模块，不逐个手工注册定义：

```python
EFFECT_MODULES = ("effects.campfire", "effects.weather")
COMPONENT_MODULES = ("components.weather",)
```

loader 按这里的顺序导入模块，并只收集带 `@scenario_effect` 或
`@scenario_component` 标记的定义。它把收集结果写入这次 Runtime 新建的 Catalog；
另一个 Runtime 会新建另一份 Catalog。入口文件和被导入模块均不得修改全局注册表。

## 后续实施顺序

### 阶段 3：数据型 ScenarioPackage

新增 `KERN.scenario` 的 manifest、package、loader 和 legacy adapter。loader 复用
现有 `load_data_bundle(...)`，不复制另一套数据读取逻辑。

`KernRuntime.from_config(...)` 识别新的 `scenario` 配置；缺失时通过 legacy adapter
把当前 config 转成内存 manifest。新增 `KernRuntime.from_loaded_scenario(...)` 集中
Runtime 装配。

验收：独立目录的数据场景可加载；路径逃逸和 manifest 错误有明确报错；新旧入口产生
等价的 DataBundle/WorldState；本阶段绝不导入场景 Python。

### 阶段 4：受信任场景 Effect

扩展 loader 只执行场景根目录 `extensions.py`，读取其中的 `EFFECT_MODULES`，并按
声明顺序导入相对模块。它从模块中收集带 `@scenario_effect` 标记的定义，注册到 core
EffectCatalog 的可变 clone。场景 Effect 必须使用强制命名空间，不能覆盖 core ID；
注册结束后冻结 Catalog。

授权入口使用 `allow_scenario_code`，默认 `false`。lint 与 executor 必须获得同一个
扩展后的 Catalog。

验收：未授权代码场景被拒绝；导入、命名空间和 ID 冲突有明确错误；场景 Effect 在
单 effect 和 bundle 事务中与 core Effect 有相同语义；不同 Runtime 的扩展相互隔离。

### 阶段 5：受信任场景组件和 codec

先读取 `extensions.py` 的 `COMPONENT_MODULES`，按声明顺序发现带
`@scenario_component` 标记的组件，再加载 Effect。组件只能是纯数据 dataclass；默认
采用 `DataclassCodec`，特殊转换才允许场景提供 codec。ComponentCatalog 在 build 和
restore 前冻结并被两者共用。

代码场景声明了有类型组件而代码未获授权时，拒绝加载整个场景，不能静默降级为
`CustomComponent`。

验收：自定义组件能由模板构造、被 query/effect 读取或修改，并在 checkpoint 后保留
类型和值；不修改 core builder 或 checkpoint；Catalog 隔离成立。

### 阶段 6：archive 身份与可复现性

snapshot meta 至少保存：

```json
{
  "scenario_id": "camping",
  "scenario_version": "1.0.0",
  "scenario_schema_version": "kern.scenario.v1",
  "scenario_content_hash": "...",
  "effect_ids": ["camping:CampfireTick"],
  "component_ids": ["camping:CampfireComponent"]
}
```

content hash 覆盖 manifest、被引用 JSON 和已加载 Python 源文件。恢复时先加载并验证
场景，再解码 checkpoint；场景 ID、schema、能力或 hash 不匹配默认拒绝。core-only
legacy checkpoint 继续使用现有路径并标记为 legacy identity。

验收：相同场景可恢复；旧代码 checkpoint 在不匹配时给出期望值与实际值；开发模式
override 必须被显式记录。

### 阶段 7：Camping 真实迁移

先复制 Camping 到 `Scenarios/Camping/`，保持 legacy 数据和 config 可用。比较两种
入口的初始世界状态、固定 tick 的关键事件和 checkpoint round-trip。稳定后再决定
旧 `Data/Camping` 的弃用时间。

验收：package lint、no-LLM smoke、checkpoint round-trip 通过；legacy config 在明确
兼容期内继续工作。

## 测试和兼容约束

每个阶段独立提交、独立验证。至少运行：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.example.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.smoke.json
```

保持兼容：当前 runtime config、当前 `Data/` 布局、现有效果 JSON 形状、无命名空间
core Effect ID、未知组件 `CustomComponent` 回退、以及不依赖场景代码的旧 checkpoint
恢复。

迁移过程中不要顺手修改任务生命周期、Bundle 控制流、LLM workflow、runtime context
或场景数值。发现的无关问题单独记录并用最小测试固定现状。
