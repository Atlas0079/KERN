# KERN ScenarioPackage 迁移实施计划

> 状态：待实施
>
> 编写日期：2026-07-11
>
> 目标读者：后续负责实际迁移的 coding agent 与项目维护者

## 1. 背景与决策

KERN 当前把场景数据放在仓库级 `Data/` 中，通过 runtime config 分别指定 world、
recipes、reactions、entity template 目录和 named bundles。所有正式 Effect 由全局
`KERN.effect_contract.EFFECT_SPECS` 注册，所有建模组件由
`KERN.data.builder._build_component(...)` 识别。

这种结构适合只有内置能力的数据场景，但无法让一个场景完整携带自己的额外行为：

- 场景新增 Effect 必须修改 KERN 中央注册表和 executor 模块。
- 场景新增有类型的纯数据组件必须修改 builder、checkpoint 和类型声明。
- 场景文件离开当前仓库布局后不能独立加载。
- 全局 Effect 注册无法隔离同一进程中的不同场景。
- 场景身份、代码版本和 checkpoint 之间没有正式对应关系。

本计划采用以下产品和架构决策：

1. KERN 保留一组小而稳定的默认 Effect 和组件。
2. Bundle 继续是有限的声明式顺序组合，不继续扩张为通用脚本语言。
3. 复杂且可命名的行为通过场景自带 Effect 实现。
4. 组件继续是以数据为中心的状态对象；世界行为留在 Effect/System 中。
5. 场景可以是纯数据包，也可以是包含受信任 Python 代码的代码场景包。
6. Effect 和组件在执行时仍需要内部索引，但场景作者不再修改中央注册表。
7. Catalog 属于单个 Runtime，不能使用会跨场景污染的全局可变注册表。
8. 迁移必须渐进进行，现有 runtime config 和 `Data/` 在迁移期保持可用。

当前 Effect 能力和分类基线见 `docs/effect_capability_inventory.md`。

## 2. 目标结果

迁移完成后，KERN 应支持：

```text
KERN core capabilities
+ one ScenarioPackage
= one isolated runnable world
```

一个场景包可以携带：

- 场景 manifest。
- World、Recipes、Reactions、Bundles 和 entity templates。
- 可选的场景 Effect。
- 可选的场景纯数据组件和 component codec。
- 场景自己的测试。

核心加载结果为：

```text
LoadedScenario
├─ ScenarioManifest
├─ DataBundle
├─ EffectCatalog
└─ ComponentCatalog
```

`KernRuntime`、`WorldExecutor`、world builder、checkpoint restore 和 scenario lint
必须使用同一个 `LoadedScenario` 所拥有的 Catalog。

## 3. 非目标

本次迁移不包含：

- 在线插件市场。
- 自动下载或安装 Python 包。
- 不受信任 Python 代码的安全沙箱。
- Effect 或组件热加载。
- 运行过程中替换 Effect 实现。
- 场景依赖解析和版本求解器。
- 允许场景静默覆盖 KERN 默认 Effect 或组件。
- 场景可视化编辑器。
- 重写 Bundle、Recipe、Reaction 或 Query DSL。
- 在迁移过程中顺便删除现有 Effect。
- 把社交平台重新作为主线需求。

## 4. 术语

### ScenarioPackage

磁盘上的完整场景目录。包含 manifest、数据和可选代码。

### ScenarioManifest

描述场景 ID、版本、数据入口、代码入口和 KERN 兼容范围的静态文件。

### LoadedScenario

`ScenarioPackageLoader` 的内存结果，包含已加载数据和已经冻结的 Catalog。

### EffectCatalog

当前 Runtime 可用 Effect ID 到 `EffectSpec` 的映射。它是执行和 lint 的共同事实来源。

### ComponentCatalog

当前 Runtime 可用组件 ID 到 `ComponentSpec`/codec 的映射。它是 builder、override、
checkpoint serialization 和 restore 的共同事实来源。

### 数据场景

不包含 Python，只能使用 KERN 默认能力和 `CustomComponent`。

### 代码场景

包含 Python Effect 或有类型组件。加载它等同于执行本机代码，必须显式信任。

## 5. 目标目录格式

第一版目录约定：

```text
Scenarios/
└─ Camping/
   ├─ scenario.json
   ├─ Data/
   │  ├─ World.json
   │  ├─ Recipes.json
   │  ├─ Reactions.json
   │  ├─ Bundles.json
   │  └─ Entities/
   │     ├─ Agents.json
   │     └─ Items.json
   ├─ logic/
   │  ├─ effects/
   │  │  ├─ campfire_tick.py
   │  │  └─ repair_shelter.py
   │  └─ components/
   │     └─ campfire.py
   └─ tests/
      ├─ test_effects.py
      └─ test_checkpoint_roundtrip.py
```

`logic/` 是可选目录。没有该目录的场景默认为数据场景。

建议的 `scenario.json` 第一版格式：

```json
{
  "schema_version": "kern.scenario.v1",
  "id": "camping",
  "version": "1.0.0",
  "kern_version": ">=0.1",
  "data": {
    "world": "Data/World.json",
    "recipes": ["Data/Recipes.json"],
    "reactions": ["Data/Reactions.json"],
    "bundles": ["Data/Bundles.json"],
    "entity_dirs": ["Data/Entities"]
  },
  "logic": {
    "effects_dir": "logic/effects",
    "components_dir": "logic/components"
  }
}
```

约束：

- `id` 必须为稳定的小写标识符，建议匹配 `[a-z][a-z0-9_-]*`。
- manifest 中所有路径相对于场景包根目录解析。
- 路径解析后必须仍位于场景包根目录内，拒绝 `..` 路径逃逸。
- `logic` 可省略；省略时不加载任何 Python。
- 代码存在与否应以实际目录和 manifest 共同判断，不能只相信布尔字段。

## 6. Runtime config 与场景 manifest 的职责

两者不能混为一个文件。

Scenario manifest 描述稳定内容：

- 场景身份和版本。
- 数据入口。
- 场景代码入口。
- 所需 KERN 兼容范围。

Runtime config 描述单次运行：

- 使用哪个场景。
- 是否使用 LLM、哪个模型和凭据。
- tick 上限。
- checkpoint 位置。
- 日志设置。
- 本次运行的 provider/runtime overrides。

目标 runtime config：

```json
{
  "scenario": "Scenarios/Camping",
  "env": {
    "USE_LLM": "1",
    "MAX_TICKS": "100",
    "CHECKPOINT_DIR": "checkpoints/camping"
  }
}
```

迁移期继续接受当前 `WORLD_JSON`、`RECIPES_JSONS` 等字段，由
`LegacyScenarioAdapter` 生成内存中的 manifest/DataBundle；不要在第一阶段立即移动
现有文件。

## 7. 目标接口草案

### 7.1 EffectSpec

第一阶段先兼容现有 module/binder/handler 命名约定，避免同时重写 43 个 Effect：

```python
@dataclass(frozen=True)
class EffectSpec:
    effect_id: str
    module: str = ""
    binder_name: str = ""
    handler_name: str = ""
    binder: BindCallable | None = None
    handler: HandlerCallable | None = None
    visibility: str = "public"       # public | engine
    origin: str = "core"             # core | scenario
    side_effect: str = "world"       # world | runtime | external
    allows_child_bundle: bool = False
    emits: tuple[str, ...] = ()
    version: str = "1"
```

同一 `EffectSpec` 可使用直接 callable，也可使用现有 module 字符串延迟解析。后续场景
Effect 优先使用 callable；核心迁移初期继续使用 module 字符串。

### 7.2 EffectCatalog

```python
class EffectCatalog:
    def register(self, spec: EffectSpec) -> None: ...
    def contains(self, effect_id: str) -> bool: ...
    def require(self, effect_id: str) -> EffectSpec: ...
    def resolve_binder(self, effect_id: str) -> BindCallable: ...
    def resolve_handler(self, effect_id: str) -> HandlerCallable: ...
    def effect_ids(self) -> frozenset[str]: ...
    def freeze(self) -> None: ...
    def clone_mutable(self) -> EffectCatalog: ...
```

必须满足：

- 重复 ID 默认报错。
- 场景不能覆盖 core ID。
- freeze 后 `register()` 报错。
- Catalog 不依赖模块级可变状态。
- callable 解析失败时保留 Effect ID 和明确错误原因。
- 两个 Catalog 在同一进程互不影响。

核心 Catalog 由纯函数构建：

```python
def build_core_effect_catalog() -> EffectCatalog:
    ...
```

### 7.3 ComponentSpec 与 ComponentCodec

组件保持纯数据定位。codec 只负责数据转换，不负责世界行为：

```python
class ComponentCodec(Protocol):
    def build(self, raw: Any) -> Any: ...
    def serialize(self, component: Any) -> dict[str, Any]: ...
    def apply_snapshot(self, component: Any, patch: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class ComponentSpec:
    component_id: str
    component_type: type
    codec: ComponentCodec
    origin: str = "core"
    version: str = "1"
```

### 7.4 ComponentCatalog

```python
class ComponentCatalog:
    def register(self, spec: ComponentSpec) -> None: ...
    def build(self, component_id: str, raw: Any) -> Any: ...
    def serialize(self, component_id: str, component: Any) -> dict[str, Any]: ...
    def apply_snapshot(self, component_id: str, component: Any, patch: dict[str, Any]) -> Any: ...
    def freeze(self) -> None: ...
```

未知组件必须继续使用：

```python
CustomComponent(data=raw_dict)
```

简单 dataclass 使用通用 codec。只有 `ContainerComponent`、
`DecisionArbiterComponent`、`TaskHostComponent` 等具有特殊嵌套或恢复语义的组件使用
专用 codec。

### 7.5 LoadedScenario

```python
@dataclass(frozen=True)
class LoadedScenario:
    manifest: ScenarioManifest
    data_bundle: DataBundle
    effect_catalog: EffectCatalog
    component_catalog: ComponentCatalog
    content_hash: str
    contains_code: bool
```

### 7.6 KernRuntime

最终构造路径：

```python
loaded = ScenarioPackageLoader(...).load(
    scenario_path,
    allow_scenario_code=False,
)

runtime = KernRuntime.from_loaded_scenario(
    loaded,
    runtime_config,
)
```

`KernRuntime.from_config(...)` 保留，内部解析新旧配置后统一产生 `LoadedScenario`。

## 8. 场景代码发现约定

目标是让场景作者无需编辑中央注册表，但运行时内部仍建立 Catalog。

### 8.1 Effect 自动发现

场景 Effect 文件定义 `EffectDefinition` 子类：

```python
class CampfireTick(EffectDefinition):
    effect_id = "camping:CampfireTick"
    visibility = "public"
    side_effect = "world"
    emits = ("CampfireFuelConsumed", "CampfireExtinguished")

    fields = {
        "target": EntityRefField(required=True),
        "fuel_cost": FloatField(default=1.0, resolve_param=True),
    }

    def execute(self, executor, ws, data, context):
        ...
```

加载器按文件名排序导入 `logic/effects/*.py`，只收集：

- 在该模块中定义的对象，而不是从其他模块导入的类。
- `EffectDefinition` 的非抽象子类。
- ID 前缀等于 `{scenario_id}:` 的 Effect。

简单 Effect 由 `fields` 自动生成 binder；复杂 Effect 可覆盖 `bind(...)`。不得要求
作者再维护单独的注册列表。

### 8.2 组件自动发现

场景组件必须是 dataclass 或满足明确的纯数据标记：

```python
@scenario_component("camping:CampfireComponent")
@dataclass
class CampfireComponent:
    fuel: float = 0.0
    burning: bool = False
    heat: float = 0.0
```

加载器按文件名排序导入 `logic/components/*.py`，收集当前模块定义且带组件标记的类。
默认使用 dataclass codec。复杂组件可通过类属性显式提供 codec。

组件不得：

- 自行调度 tick。
- 直接触发 Reaction。
- 持有 LLM/provider/数据库连接。
- 在序列化字段中保存不可重建的进程对象。

局部不变量方法可以保留，但世界行为必须位于 Effect/System。

### 8.3 导入实现要求

- 使用由场景 ID 和内容 hash 组成的唯一模块 namespace，避免两个场景模块重名。
- 不修改全局 `sys.path` 后遗留场景路径。
- 导入顺序稳定：先 components，后 effects；各目录内按相对路径排序。
- 任意导入异常必须终止场景加载并指明文件。
- `allow_scenario_code=False` 时，如果发现代码目录，必须显式报错，不能静默忽略。

## 9. 命名与冲突规则

为兼容现有数据，KERN core Effect 和组件暂时保留无前缀名称：

```text
AddStatus
MoveEntity
CreatureComponent
```

场景定义必须使用命名空间：

```text
camping:CampfireTick
camping:CampfireComponent
arena:ResolveFishing
```

规则：

- 场景 ID 必须与前缀一致。
- 场景不能注册无前缀名称。
- 场景不能覆盖任何已有 ID。
- 同一个包中重复定义立即报错。
- checkpoint 记录完整 ID，不保存模糊短名称。

## 10. 分阶段实施计划

每一阶段应独立提交、独立验证。后续阶段不得借机重写前一阶段已稳定的语义。

### 阶段 0：建立行为基线

目标：在结构迁移前锁定当前行为。

新增或补强测试：

- 43 个 core Effect 均能解析 binder 和 handler。
- unknown Effect 返回现有 contract error。
- Effect 失败和 Bundle 失败的回滚行为。
- scenario lint 对已知/未知 Effect 的判断。
- 当前三个正式配置的 lint。
- Camping no-LLM smoke。
- 当前组件 build/snapshot/rebuild round-trip。

建议文件：

```text
tests/test_effect_catalog.py
tests/test_component_catalog.py
tests/test_scenario_package.py
```

验收标准：

- 迁移前新增测试全部通过。
- 测试不依赖网络或 LLM。
- 明确记录当前有意保留的错误语义，不在基线阶段顺便修复。

建议提交：

```text
Characterize effect and component loading contracts
```

### 阶段 1：引入 runtime 级 EffectCatalog

目标：消除执行路径对全局 `EFFECT_TYPES` 的直接依赖，行为保持不变。

新增文件建议：

```text
KERN/effects/__init__.py
KERN/effects/spec.py
KERN/effects/catalog.py
KERN/effects/core.py
```

修改范围：

- `KERN/effect_contract.py`
- `KERN/executor/_effect_binder.py`
- `KERN/executor/executor.py`
- `KERN/runtime.py`
- `tools/scenario_lint.py`
- 构造 `WorldExecutor()` 的测试和辅助代码

实施步骤：

1. 定义 `EffectSpec` 和 `EffectCatalog`。
2. 把当前 `EFFECT_SPECS` 转换为 `build_core_effect_catalog()` 的输入。
3. 保留现有 module、binder/handler 命名推导和延迟 import。
4. `WorldExecutor` 增加 `effect_catalog` 字段。
5. 为兼容大量直接测试，`WorldExecutor()` 默认创建一个新的 core Catalog，而不是
   引用全局单例。
6. `WorldExecutor.execute(...)` 从自己的 Catalog 查询 spec/handler。
7. `bind_effect_input(...)` 接收 Catalog，并从同一 Catalog 查询 binder。
8. `KernRuntime.from_config(...)` 创建一次 core Catalog并传给 executor。
9. scenario lint 接收 Catalog；CLI 未传入时使用新的 core Catalog。
10. Catalog 在 Runtime 开始运行前冻结。
11. 旧 `EFFECT_TYPES` 可以短期保留为只读兼容视图，但执行路径不得依赖它；在后续
    阶段删除。

新增测试：

- 两个 Catalog 注册不同测试 Effect 时互不影响。
- frozen Catalog 拒绝写入。
- 重复 ID 报明确错误。
- core Effect 不可被覆盖。
- executor 和 lint 使用同一 Catalog 时得到一致判断。

验收标准：

- 43 个 core Effect 的输入、handler 和事件行为不变。
- executor 不再直接 import `EFFECT_TYPES`。
- binder 不再直接 import `EFFECT_TYPES`。
- lint 可以显式使用调用方传入的 Catalog。
- 全部现有测试通过。
- 三个正式配置 lint 通过。
- Camping smoke 通过。

建议提交：

```text
Introduce runtime-scoped effect catalog
```

### 阶段 2：引入 ComponentCatalog 和 codec

目标：让组件构建、override 和 checkpoint 共用一个事实来源，为场景组件做准备。

新增文件建议：

```text
KERN/components/__init__.py
KERN/components/spec.py
KERN/components/catalog.py
KERN/components/codecs.py
KERN/components/core.py
```

不要移动现有 `KERN/models/components/`；新目录只承载注册和 codec 模块，避免把数据
模型与加载机制混为一体。若命名容易混淆，可改用 `KERN/component_catalog/`。

修改范围：

- `KERN/data/builder.py`
- `KERN/data/checkpoint.py`
- `KERN/models/entity.py`
- `KERN/runtime.py`
- archive/checkpoint tests

实施步骤：

1. 定义 `ComponentSpec`、`ComponentCodec` 和 `ComponentCatalog`。
2. 先为简单 dataclass 提供 generic codec。
3. 为 Container、DecisionArbiter、TaskHost 建立特殊 codec。
4. 按现有行为迁移 `_build_component(...)` 中的构造规则。
5. 按现有行为迁移 `apply_component_overrides(...)` 特例。
6. 按现有行为迁移 `_serialize_component_override(...)` 特例。
7. builder 和 checkpoint 显式接收同一个 ComponentCatalog。
8. 未注册 ID 继续构建 `CustomComponent`。
9. 将 `Entity.ComponentValue` 的封闭 union 调整为允许 Catalog 提供的纯数据对象；运行
   时不应依赖这个 union 识别组件。
10. restore 必须使用与原运行相同的 Catalog。

新增测试至少覆盖：

- 每个 core 组件 JSON -> object -> JSON round-trip。
- Container slots/config/items。
- TaskHost 中的 tasks 和生命周期 Bundle。
- DecisionArbiter rules/presets/runtime state。
- Memory、Screen、Status 等有状态 dataclass。
- 未注册组件回退为 CustomComponent。
- 注册测试 dataclass 后恢复为其原类型。
- 同一进程两个 ComponentCatalog 隔离。

验收标准：

- Builder 不再维护组件名称级的长 `if` 链。
- Checkpoint 不再独立维护同一批组件字段知识。
- 三个正式配置 build/snapshot/rebuild 完全一致。
- archive restore tests 通过。
- 未知场景组件行为不变。

建议提交：

```text
Centralize component construction and checkpoint codecs
```

### 阶段 3：实现数据型 ScenarioPackage

目标：统一场景加载入口，第一版只加载 JSON，不执行 Python。

新增文件建议：

```text
KERN/scenario/__init__.py
KERN/scenario/manifest.py
KERN/scenario/package.py
KERN/scenario/loader.py
KERN/scenario/legacy.py
```

实施步骤：

1. 定义 manifest schema 和路径安全校验。
2. 定义 `LoadedScenario`。
3. 将 `load_data_bundle(...)` 的文件读取逻辑复用到场景包路径；不要复制一套 loader。
4. `ScenarioPackageLoader` 从 core Catalog 开始构建 LoadedScenario。
5. 实现 `LegacyScenarioAdapter`，把当前 config 字段转换成内存 manifest。
6. `KernRuntime.from_config(...)` 识别新 `scenario` 字段；没有时走 legacy adapter。
7. 新增 `KernRuntime.from_loaded_scenario(...)`，集中 runtime assembly。
8. checkpoint、lint 和 executor 使用 LoadedScenario 中的 Catalog。

新增一个最小数据测试场景：

```text
tests/fixtures/scenarios/data_only/
```

验收标准：

- 数据场景可从独立目录加载。
- 新旧入口生成等价的 DataBundle/WorldState。
- 场景路径逃逸被拒绝。
- 缺少文件和错误 schema 有明确文件位置。
- 现有 runtime config 全部继续工作。
- 此阶段不导入场景 Python。

建议提交：

```text
Add data-only scenario package loading
```

### 阶段 4：实现代码场景 Effect 自动发现

目标：场景可携带 Effect，无需编辑 KERN 中央注册表。

新增文件建议：

```text
KERN/scenario/effect_definition.py
KERN/scenario/extension_loader.py
KERN/effects/fields.py
```

实施步骤：

1. 定义 `EffectDefinition` 基类和字段声明类型。
2. 为简单字段声明生成 binder。
3. 允许复杂定义覆盖 `bind(...)`。
4. extension loader 按稳定顺序导入 Effect 文件并收集类。
5. 强制场景命名空间。
6. 把场景 Effect 添加到 core Catalog 的可变 clone，检查冲突后 freeze。
7. `allow_scenario_code` 默认 false。
8. CLI 增加明确的 `--allow-scenario-code`，SDK 使用同名布尔参数。
9. lint 与 executor 使用扩展后的同一 Catalog。

测试 fixture：

```text
tests/fixtures/scenarios/code_effect/
```

测试内容：

- 一个简单字段 Effect。
- 一个自定义 binder Effect。
- Recipe 和 Reaction 能引用场景 Effect。
- 未授权代码场景拒绝加载。
- 重复 ID、错误 namespace、导入异常均明确失败。
- 场景 Effect 成功参与单 Effect 和 Bundle 事务。
- 场景 A 的 Effect 不会出现在场景 B Runtime。
- 场景不能覆盖 `AddStatus` 等 core Effect。

验收标准：

- 场景作者只需在约定目录定义 Effect 类。
- 不需要维护中央注册列表。
- 代码加载是显式授权行为。
- 运行开始后 Catalog 冻结。

建议提交：

```text
Load scenario-owned effects into isolated catalogs
```

### 阶段 5：实现代码场景组件自动发现

目标：场景可携带有类型的纯数据组件，并能完整 checkpoint round-trip。

实施步骤：

1. 定义 `scenario_component(...)` 标记或等价的 `ComponentDefinition`。
2. 自动发现 dataclass 组件。
3. 默认使用 generic dataclass codec。
4. 允许场景显式提供特殊 codec。
5. 组件先于 Effect 导入。
6. ComponentCatalog 扩展后冻结并用于 build/restore。
7. Query、path resolution 和 `ModifyProperty` 不应要求组件来自 core 类型 union。

测试 fixture：

```text
tests/fixtures/scenarios/code_component/
```

测试至少覆盖：

- 自定义 dataclass 从 entity template 构建。
- `ModifyProperty` 修改字段。
- Query/condition 读取字段。
- 场景 Effect 使用自定义组件类型。
- checkpoint 保存、恢复后仍是原组件类型。
- 未加载代码时同名 JSON 只作为 CustomComponent 或因 manifest 需要代码而明确失败；
  两种策略必须固定一种，不可静默改变存档类型。
- 不合法的组件字段给出场景文件位置。

建议策略：代码场景声明的有类型组件在未授权时直接拒绝加载整个场景，不降级为
CustomComponent，避免悄悄改变语义。

验收标准：

- 组件仍为纯数据，不拥有世界调度能力。
- 场景组件不要求修改 core builder/checkpoint。
- round-trip 保留类型和值。
- Catalog 隔离成立。

建议提交：

```text
Load scenario-owned data components and codecs
```

### 阶段 6：场景身份、archive 与可复现性

目标：让 checkpoint 知道自己依赖哪个场景和代码版本。

archive/snapshot meta 至少记录：

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

content hash 至少覆盖：

- manifest 规范化内容。
- 被 manifest 引用的场景 JSON 文件。
- 被加载的场景 Python 源文件。

恢复策略：

- scenario ID 不同：拒绝恢复。
- manifest schema 不支持：拒绝恢复。
- 缺少所需 Effect/组件：拒绝恢复并列出 ID。
- 版本或 hash 不同：第一版默认拒绝；可提供显式开发模式 override，但必须记录。
- core-only legacy checkpoint：继续使用现有恢复路径，并标记 legacy identity。

验收标准：

- 相同场景和代码可恢复。
- 修改场景 Effect 后旧 checkpoint 明确拒绝或要求 override。
- 错误信息包含期望值和实际值。

建议提交：

```text
Record scenario identity in archives and restore checks
```

### 阶段 7：迁移一个正式场景并整理兼容层

目标：用真实场景验证包模式，而非只依赖测试 fixture。

建议首个迁移对象：Camping。原因：

- 无需 LLM 即可验证。
- 已有稳定 smoke config。
- 数据规模适中。
- 可以先作为数据场景迁移，再添加一个很小的场景 Effect/组件验证代码扩展。

步骤：

1. 复制或移动 Camping 数据到 `Scenarios/Camping/Data/`；第一轮优先复制并校验，
   避免立即破坏旧路径。
2. 新增 manifest。
3. 新增 scenario-package runtime config。
4. 对比 legacy 和 package 两种入口的初始 WorldState hash。
5. 运行相同 tick 数并比较关键事件/世界状态。
6. 选取真正属于 Camping 的小能力作为场景 Effect 示例，不为演示凭空制造抽象。
7. 当 package 路径稳定后，再决定旧 `Data/Camping` 的弃用时间。

验收标准：

- Camping package lint 通过。
- no-LLM smoke 通过。
- checkpoint round-trip 通过。
- legacy config 在明确的兼容期内仍通过。
- 文档说明如何创建新的数据场景和代码场景。

建议提交：

```text
Migrate Camping to a self-contained scenario package
```

## 11. 测试矩阵

每阶段完成后至少运行：

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall KERN tools default_orchestrator.py tests
python tools\scenario_lint.py --config runtime_config.camping.smoke.json
python tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
python tools\scenario_lint.py --config runtime_config.example.json
python default_orchestrator.py --config runtime_config.camping.smoke.json
```

当前环境若系统 `python` 不可用，可使用已确认的 bundled runtime：

```powershell
& 'C:\Users\atlas\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p "test_*.py"
```

新增测试分层：

| 层级 | 主要验证 |
| --- | --- |
| Catalog unit tests | 注册、冲突、freeze、隔离、解析错误 |
| Effect contract tests | binder、handler、事件、事务回滚 |
| Component codec tests | build、serialize、override、round-trip |
| Scenario loader tests | manifest、路径、代码授权、稳定导入顺序 |
| Runtime integration | LoadedScenario 到 tick loop 的完整装配 |
| Archive integration | 场景身份、版本/hash、restore |
| Real scenario smoke | Camping legacy/package 行为一致 |

## 12. 兼容和弃用策略

### 必须保持兼容

- 当前 runtime config。
- 当前 `Data/` 布局。
- 现有 Effect JSON 形状。
- 现有无命名空间 core Effect ID。
- 未知组件回退为 `CustomComponent`。
- 现有 checkpoint 在不依赖场景代码时的恢复。

### 可以分阶段弃用

- 执行路径直接读取全局 `EFFECT_TYPES`。
- builder 中组件名称 `if` 链。
- checkpoint 中重复的组件字段知识。
- 新场景继续使用仓库级散落配置。
- 场景专属 Effect 放在 `KERN/executor/`。

任何弃用都应先提供新路径、warning 和迁移说明，不能在同一提交中直接删除旧路径。

## 13. 安全模型

纯 JSON 场景和代码场景必须有明确区别。

代码场景拥有与 KERN 进程相同的 Python 权限，可能：

- 读取或修改文件。
- 访问网络。
- 读取环境变量和凭据。
- 启动子进程。

第一版不尝试用 Python 技巧构造不可信沙箱。正确策略是：

- 默认禁止加载场景代码。
- CLI/SDK 显式授权。
- 加载前显示场景路径和代码文件清单。
- archive 记录代码 hash。
- 文档明确“只运行受信任场景”。

场景 JSON 本身不得指定任意系统 module 路径并自动 import。只能加载场景包约定目录
内、经过路径检查的 Python 文件。

## 14. 主要风险与控制措施

### 风险：一次迁移同时触及 executor、builder、checkpoint 和 lint

控制：EffectCatalog、ComponentCatalog、ScenarioPackage 分开提交；每阶段先补行为测试。

### 风险：Catalog 只是给全局字典包一层壳

控制：测试两个 Runtime/Catalog 同进程隔离；执行路径必须从实例依赖读取。

### 风险：场景组件把行为带回组件

控制：组件 discovery 只接受纯数据类；世界行为继续由 Effect/System 承担。

### 风险：自动扫描带来隐式和不可预测行为

控制：目录固定、文件排序、对象筛选规则固定、命名空间强制、导入错误立即失败。

### 风险：场景代码破坏 Bundle 事务

控制：场景 Effect 必须通过同一个 `WorldExecutor`；禁止自行发布 settlement；外部副
作用必须声明且单独处理。

### 风险：旧 checkpoint 在新代码下静默改变语义

控制：记录 scenario identity/version/hash；缺少或不匹配时默认拒绝。

### 风险：为了支持扩展把接口设计得过大

控制：场景作者面对的主要接口只有 `EffectDefinition`、纯数据组件标记和可选 codec；
发现、冲突、冻结、lint 与 archive 集成隐藏在 ScenarioPackage 模块内。

## 15. 实施时禁止顺手处理的事项

为了保持提交可审查，迁移过程中不要同时：

- 删除 `InvokeBundle`、`RandomBundle` 或 `ApplyToQuery`。
- 改变任务生命周期语义。
- 修复与当前阶段无关的 Effect 业务问题。
- 把社交平台代码移动到新扩展包；等通用机制稳定后另立任务。
- 修改 LLM workflow 行为。
- 重做 runtime context。
- 调整场景数值和 Recipe 内容。
- 批量格式化无关文件。

发现问题时记录为独立 follow-up，并用最小行为测试固定现状。

## 16. 下一次对话的建议起点

下一位 agent 应先完成以下检查：

1. 阅读 `docs/agent_project_memory.md`。
2. 阅读本文档和 `docs/effect_capability_inventory.md`。
3. 检查 `git status`，保留用户未跟踪文件。
4. 查看最新提交和当前分支。
5. 重新读取 `effect_contract.py`、`executor.py`、`_effect_binder.py`、runtime 和
   scenario lint 的实际代码。
6. 与用户确认本次只实施“阶段 0 + 阶段 1”，不提前进入 ComponentCatalog。
7. 先写 Catalog 隔离和兼容测试，再替换执行路径。

建议第一轮开发范围：

```text
阶段 0：行为基线
+
阶段 1：runtime-scoped EffectCatalog
```

第一轮完成定义：

- 新旧 43 个 Effect 行为一致。
- executor/binder/lint 使用同一个 Catalog。
- 两个 Catalog 可隔离。
- runtime 运行后 Catalog 冻结。
- 全套测试、三份 lint 和 Camping smoke 通过。
- 文档更新实际落地状态。
- 不加载场景 Python，不迁移组件，不移动 Data。

## 17. 总体验收标准

整个 ScenarioPackage 迁移完成时，应能证明：

1. 一个纯数据场景可以作为独立目录加载。
2. 一个受信任代码场景可以自带 Effect，无需修改 KERN core。
3. 一个受信任代码场景可以自带纯数据组件及 codec，无需修改 builder/checkpoint。
4. 场景 Effect 和组件只在该 Runtime 可见。
5. 两个不同场景可以在同一进程中构建而不污染彼此。
6. 场景代码失败、ID 冲突和未授权加载都有明确错误。
7. 场景 Effect 参与现有事务和 settlement 语义。
8. 场景组件能完整 checkpoint round-trip。
9. archive 能识别场景身份和代码版本不匹配。
10. 现有 legacy config 在迁移期继续工作。
11. Camping 通过新旧两种入口产生等价的可验证行为。
12. 新场景作者不需要编辑 KERN 中央 Effect 或组件注册代码。

本计划把 ScenarioPackage 作为一个深模块：调用方只需要给出场景路径和代码授权，
模块内部负责 manifest、数据、能力发现、Catalog 隔离、冲突检查、lint 和可复现性。
实施时应持续保护这个小接口，不把内部装配细节泄漏回 runtime config 或场景 DSL。
