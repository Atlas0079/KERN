# KERN Package 组合与可恢复性

> 状态：当前实现参考。Package 迁移阶段 0–7 已完成。

## 运行组合

一次 KERN 运行由 config 明确选择的 Package 组成。选择 Package 即表示信任它声明的
Python 代码；KERN 不提供额外的代码授权开关或 Python 沙箱。一次运行必须选择且只能选择
一个世界包，也可以选择零个或多个能力包。

```text
Runtime
├─ KERN core 能力
├─ 能力包：Weather、Crafting（可选）
└─ 世界包：Camping（World、Entities、Recipes、Reactions）
```

每个 runtime 都有独立的 `EffectCatalog` 和 `ComponentCatalog`。两者分别由 lint、
executor、world build、restore 和 archive 共用，并在执行前冻结；能力不会泄露到另一次
runtime。

## Package 格式与加载规则

config 使用顶层 `packages` 数组，`env` 保留运行时参数：

```json
{
  "packages": [
    {"path": "Packages/Weather"},
    {"path": "Packages/Camping", "world": true}
  ],
  "env": {"USE_LLM": "0"}
}
```

世界包 manifest 必须声明 `provides_world: true` 和世界数据；能力包不能声明世界数据。
Package 路径必须位于项目根目录内，Package ID 不得重复。loader 会拒绝零个或多个世界包、
路径逃逸、缺失 manifest、数据类型不匹配和 ID 冲突。

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

有扩展代码时，manifest 的入口固定为根目录 `extensions.py`：

```python
EFFECT_MODULES = ("effects.weather",)
COMPONENT_MODULES = ("components.weather",)
```

loader 只从入口声明的模块中发现带 `@package_effect` 或 `@package_component` 标记的定义。
组件及其 codec 先注册，Effect 后注册；所有 Package definition ID 都必须使用所属 Package
的命名空间。组件只能是纯数据 dataclass，默认采用 `DataclassCodec`；特殊转换由 Package
显式提供 codec。

## Archive 与 checkpoint identity

每次 Package 装配都会固定 `package_identity.v2`。它描述 runtime 实际依赖的 artifact，
不把整个 Package 目录当作指纹。identity 包含：

- 每个选中 Package 的 `kern-package.json`；
- 世界包实际读取的 world、recipe、reaction、bundle 与 entity JSON；
- 声明扩展时的 `extensions.py`，以及 `COMPONENT_MODULES` / `EFFECT_MODULES` 实际导入的
  Package-local Python 文件；
- 冻结后的 effect 与 component ID 清单。

每个 Package 的 `runtime_content_hash` 稳定地 hash 相对路径、artifact role 和文件内容。
未加载的 JSON/Python 文件不会改变 identity；上述任一 artifact 变化会阻止 v2 checkpoint
恢复。identity 在 loader 完成时保存于 `LoadedPackages`，archive 写入不会重新扫描磁盘。

archive manifest 与 snapshot metadata 使用嵌套字段：

```json
{
  "package_identity": {
    "schema_version": "package_identity.v2",
    "packages": [
      {"package_id": "camping", "version": "1.0.0", "runtime_content_hash": "…", "world": true}
    ],
    "effect_ids": ["…"],
    "component_ids": ["…"]
  }
}
```

恢复时，v2 metadata 按 artifact identity 验证；旧的顶层 v1 metadata 继续按完整目录中
`.json`/`.py` 的旧 hash 规则验证；没有 Package metadata 的历史 checkpoint 保留 legacy
restore 路径。

## Runtime snapshot

`KernRuntime.snapshots` 使用 `runtime_snapshot.v2`。每个实体包含两个组件字段：

- `component_state`：完整 canonical 状态。它遍历实体的全部组件，并调用当前 runtime 的
  `ComponentCatalog.serialize(component_id, value)`；输出与 live world state 脱离引用。
- `components`：兼容性展示投影，保留 Creature、Worker 与 Container 的既有精简形状。

`ContainerComponent`、`TaskHostComponent` 与 `DecisionArbiterComponent` 等复杂组件只通过
各自 codec 序列化；runtime 不再维护第二套按组件类型转换的 canonical 逻辑。snapshot 不保存
Python handler、codec、catalog 或 `WorldState.services`。

## 已迁移的世界包

Camping 与 SU7Crisis 是自包含世界包。SU7Crisis 保留 100-agent 生成世界，并将所需社交
recipes 和 seed 数据纳入包内；Farm、RumorSpread、CompanionRobot、SpaceWerewolf 的旧运行数据
已删除，后两者仅保留设计文档。

## 验证

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.package.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.su7_crisis.package.smoke.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.package.smoke.json
```
