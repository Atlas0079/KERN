# Runtime 组合与外部生命周期设计

> 状态：当前设计参考。本文件描述稳定边界，不保留已完成的实施步骤。

## Runtime 组合

一次运行由两类输入构成：Package 选择与运行参数。前者决定世界数据、可用的组件和 effect；后者决定 tick、provider、checkpoint 与外部 runtime 等行为。两者必须来自同一份 config，并在装配时验证一致性。

Package loader 为每次运行构造独立的 `EffectCatalog` 与 `ComponentCatalog`，加载完成后冻结。世界构建、lint、executor、archive 和 restore 共享这些 catalog，避免能力泄露或同一组件出现多套转换规则。

## 外部生命周期

外部 runtime 通过 bridge 接入，不属于 `WorldState`。bridge 以稳定 runtime ID 顺序协调以下生命周期：

- checkpoint 保存与恢复；
- bundle 提交；
- bundle 回滚；
- 运行结束时的资源关闭。

外部 adapter 失败必须以带 phase 和 runtime ID 的错误暴露。发生生命周期失败后，runtime 进入终止状态，拒绝继续推进；这比在世界状态与外部状态可能不一致时继续运行更可诊断。

## Bundle 边界

`WorldExecutor` 负责 `WorldState` transaction。嵌套 child bundle 与其外层 bundle 共享 transaction，成功事件只在最终提交后才对 reactions 可见。

外部写入的回滚能力取决于 adapter，不能假定与 `WorldState` 一样原子。effect 声明其外部行为，executor 与 lint 据此限制执行顺序；不可逆外部操作必须放在可能失败的世界 effect 之后。

## 约束

- workflow、recipe 与 reaction 产生 effect bundle，不直接写 `WorldState`。
- 不向 `WorldState.services` 随意增加依赖；复用现有 external-runtime bridge。
- checkpoint 记录运行可恢复的数据，不把 Python handler、catalog 或 services 当作快照状态。
- 外部一致性语义应由具体 adapter 和测试明确说明。
