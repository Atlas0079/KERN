# Package 组合与可恢复性

本文描述当前 Package 加载、扩展发现和 runtime identity 契约。

## 运行组合

一次运行由 config 顶层 `packages` 明确选择一个 world Package 和零个或多个 capability
Package。选择 Package 表示信任它声明的 Python 代码；KERN 不提供额外授权开关或 Python
沙箱。

```json
{
  "packages": [
    {"path": "Packages/Weather"},
    {"path": "Packages/Camping", "world": true}
  ],
  "env": {"USE_LLM": "0"}
}
```

Package 路径必须位于 project root 内，Package ID 不得重复。loader 会拒绝缺少顶层
`packages`、零个或多个 world 选择、路径逃逸、缺失 manifest、manifest 类型错误和数据 ID
冲突。

## Manifest 与数据

manifest 文件固定为 Package 根目录的 `kern-package.json`。world Package 必须声明
`provides_world: true` 和完整 world data；capability Package 不能提供 world 文件，但可以
组合 recipe、reaction 和 named bundle 数据。

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

当前可运行 world Package 是 `Packages/Camping`。其他历史场景不参与 Package 加载。

## 扩展发现

有扩展代码时，入口固定为 Package 根目录的 `extensions.py`：

```python
EFFECT_MODULES = ("effects.weather",)
COMPONENT_MODULES = ("components.weather",)
```

loader 只导入入口声明的 Package-local 模块，并只注册其中带 `@package_effect` 或
`@package_component` 标记的定义。组件和 codec 先注册，Effect 后注册。Package definition
ID 必须使用所属 Package 的命名空间。

每个 runtime 从 core definitions 建立独立的 `EffectCatalog` 和 `ComponentCatalog`，加入所选
Package 的 definitions 后冻结。lint、build、restore、executor 和 archive 共用这两个 catalog；
一个 runtime 的扩展不会泄露到另一个 runtime。

普通 Package Component 必须是纯数据 dataclass，默认使用 `DataclassCodec`。需要特殊转换时，
Package 必须显式提供 codec。

## Artifact identity

Package 装配完成后生成固定的 `package_identity.v2`。identity 只覆盖本次 runtime 实际读取
或导入的 artifact：

- 每个选中 Package 的 `kern-package.json`；
- 实际加载的 world、entity、recipe、reaction 和 bundle JSON；
- 已声明的 `extensions.py` 和实际导入的 Package-local Python 模块；
- 冻结后的 Effect ID 与 Component ID 清单。

每个 Package 的 `runtime_content_hash` 对相对路径、artifact role 和文件内容计算稳定 hash。
未加载文件不会改变 identity；已加载 artifact 改变时，v2 checkpoint 恢复会失败。identity
保存在 `LoadedPackages` 中，archive 写入时不会重新扫描磁盘。

恢复兼容规则如下：

- `package_identity.v2` 按当前 artifact identity 精确验证；
- checkpoint 必须包含精确匹配的 `package_identity.v2`；历史 v1 identity 和缺少
  Package metadata 的 checkpoint 会被拒绝。

## Runtime snapshot

`KernRuntime.snapshots` 使用 `runtime_snapshot.v2`：

- `component_state` 是全部组件经过当前 `ComponentCatalog.serialize()` 产生的 canonical 状态。

复杂组件由各自 codec 序列化。snapshot 不保存 Python Handler、codec、catalog 或
`WorldState.services`。
