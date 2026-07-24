# KERN 测试契约审计

状态：第一轮只读审计完成，尚未授权删除或重写测试
建立日期：2026-07-24
范围：`tests/test_*.py` 的 26 个测试文件

## 1. 审计原则

测试没有权威性，内核契约才有权威性；正确测试是契约的可执行证据。

测试必须从已确认的内核契约推导。测试不得要求 Decision、Workflow、
Recipe 或 Reaction 越过 `WorldExecutor` 修改世界，不得把提交前结果记录为
成功事实，也不得通过兼容断言固定尚未接受的错误模型、Diagnostics 接口或
场景政策。

本轮审计只分类，不删除测试、不修改生产代码。分类含义如下：

- **保留**：主要断言对应已确认契约，可继续作为恢复工作的安全网；
- **重写**：测试目标部分有效，但 seam、依赖注入方式或具体断言正在固定错误设计；
- **迁移/拆分**：行为可能有效，但属于 capability package、研究数据或工具边界；
- **删除**：该项断言只要求错误行为，且没有应保留的契约目标。

“删除”优先作用于具体测试或断言。只有一个文件的全部内容都没有契约价值时，
才删除整个文件。

## 2. 结论

当前没有任何一个测试文件适合未经替代就整体删除。

问题集中在少数跨模块测试：

- Workflow 测试通过 `WorldState.services` 获取执行能力或运行配置；
- Settlement 测试把 Reaction 内部状态直接写入 `interaction_log` 视为正确；
- Diagnostics 测试固定了未统一的 category 词表、WorldState service 注入和
  “基础设施错误降级为 noop”；
- LLM replan 测试要求命令编译阶段已经产生成功 interaction；
- 部分核心测试直接固定 Creature、LowNutrition 和 Camping 的领域政策。

Catalog 隔离、Bundle 回滚、Package 选择、checkpoint/archive round-trip 和
外部运行时失败终止等测试仍提供重要证据。删除这些测试会直接削弱恢复计划中的
I-03、I-05、I-06 和持久化验收。

## 3. 逐文件审计

| 测试文件 | 处置 | 契约判断 | 后续动作 |
|---|---|---|---|
| `test_agent_workflow_runtime.py` | 重写 | 记忆 patch 在决策前可见是有效目标；测试通过 `ws.services["execute"]` 和 `workflow_view_profile` 取得运行能力，固定了 I-07 中待移除的隐式 Interface。 | 改为显式 workflow runtime 依赖；证明记忆写入经过 Executor，并增加 Workflow 不直接 `record_*` 的边界检查。 |
| `test_archive.py` | 保留，清理 fixture | delta、materialize 和 restore 是有效持久化契约。测试直接 `ws.record_event()` 只用于准备数据，没有理由作为运行时生产路径范例。 | 保留三项行为；在 Event 提交接口确定后，用已提交事件 fixture 替代直接写入。 |
| `test_checkpoint_viewer_server.py` | 保留 | 只验证分析工具如何读取已存档时间，不参与世界事务。 | 保留；如果工具形成公开 API，再减少对私有方法的直接调用。 |
| `test_component_catalog.py` | 保留，局部去领域化 | runtime-scoped catalog、freeze、codec round-trip、build/archive/restore 共用 catalog 都是已确认契约。LowNutrition 示例和“全部核心组件”会随能力迁移变化，但测试主体没有要求它必须留在核心。 | 保留；用中性规则替换 LowNutrition 示例，领域组件迁移后由 package 测试覆盖。 |
| `test_creature_component.py` | 迁移 | Creature 初始化属于 Survival 能力政策，不足以证明它是最小内核原语。 | 随 Creature capability package 迁移测试；未选择该 package 时补充 catalog 不可见测试。 |
| `test_diagnostics.py` | 删除并替换 | 多条诊断记录、独立 kind 词表和 `diagnostic_recorder` service 已被统一 KernFailure 与单次 failure.json 报告取代。 | 使用 `test_failure_and_effect_records.py` 验证唯一 Failure、完整上下文和 EffectRecord。 |
| `test_dynamic_text.py` | 重写 | 单次渲染、仅支持显式文本字段是已确认约束；当前允许路径、Corpse 示例和直接 handler 调用固定了 CR-11 尚未确定的作者契约。 | 保留渲染一次与未知引用失败；改用中性实体模板，并通过 Binder/Executor 公共 seam 测试支持字段。 |
| `test_effect_binder_defaults.py` | 重写 | 默认参数语法可能有效，但只测试私有 `_resolve_param_token`，无法证明 Binder 的公开输入输出契约。 | 通过实际 Effect binder 或 lint 测试 `param:name:default`；在参数语法确认前不扩大兼容行为。 |
| `test_effect_catalog.py` | 保留 | catalog 隔离、冻结、extension resolution、lint 共用 catalog 和外部副作用排序都符合当前权威契约。 | 保留；统一 Failure 后只更新错误 envelope 断言，不降低错误信息要求。 |
| `test_environment_scopes.py` | 迁移/待核心清单决定 | 环境 scope 机制可能是内核原语，但天气、光照、条件过期和感知组合已经形成领域能力。 | 拆成通用 scope 机制测试和 environment capability 行为测试；不要用现有文件证明整组定义必须留在核心。 |
| `test_executor_transactions.py` | 保留并扩充 | 直接保护 I-03：父子 Bundle、单 Effect、外部 compensatable/irreversible 写入和失败回滚。 | 保留全部主体；新增回滚不留下成功 Event/Interaction 的跨模块红灯测试。 |
| `test_external_runtime_bridge.py` | 重写，保留主体 | adapter 路由、receipt、commit/rollback、checkpoint lifecycle 和 terminal runtime 是有效目标；`kind`、`recoverable` 等旧错误字段需服从统一 Failure。 | 保留生命周期行为；重写错误 schema 断言，并确认 bridge 注入不扩展新的 service key。 |
| `test_gametime.py` | 保留 | 时间锚点、真实日历和 checkpoint 序列化是稳定的数据/持久化行为。 | 保留。 |
| `test_interrupt_presets.py` | 迁移/拆分 | preset 切换机制可能属于 agent workflow；LowNutrition 是 Survival 领域政策。 | 保留通用 preset 选择测试，迁移 LowNutrition rule 与 Creature fixture。 |
| `test_llm_gateway.py` | 保留 | 独立工具的负载路由、失败冷却和 stream 拒绝，不改变 WorldState。 | 保留。 |
| `test_llm_request_extra.py` | 保留 | 验证 LLM 客户端参数透传，与世界事务无冲突。 | 保留。 |
| `test_llm_ungroundable_replan.py` | 重写 | “ungroundable 后重新规划”是有效 provider 行为；通过 `ws.services["execute"]` 应用记忆并要求编译后已有 success interaction，固定了 CR-01/CR-07 的错误路径。 | 将 provider replan 作为纯决策测试；记忆提交和 interaction 另由 Action/Executor 集成测试覆盖。 |
| `test_modify_property_clamp.py` | 拆分 | dataclass 自声明 clamp 是可复用机制；Creature 数值上下限属于 Survival 能力。 | 用 `HeatComponent` 保留通用机制测试；Creature 用例迁入 capability package。 |
| `test_package_loading.py` | 保留 | 直接保护 runtime-scoped catalogs、选择隔离、manifest 校验、extension discovery 和 `package_identity.v2`。 | 保留；领域迁移时增加 capability 被选择/未选择的对应测试。 |
| `test_provider_catalog.py` | 重写 | provider 优先级和 named profile 有价值；直接以字符串 services bag 作为路由接口会固化 I-07 的问题。 | 先确定小型 provider registry/interface，再把优先级断言迁到该公开 seam。 |
| `test_social_removal_contract.py` | 迁移/拆分 | 核心 catalog 不暴露已移除社交定义直接保护 I-06；历史研究数据的精确记录数量不属于内核单元测试。 | 保留 catalog 隔离测试；把研究数据完整性测试移到 `research_data` 对应验证入口。 |
| `test_task_lifecycle.py` | 保留并扩充 | start/tick/cleanup/completion child bundle 在 Executor 事务内执行，以及失败回滚 progress，直接保护任务事务边界。 | 保留；CR-13 定型后增加生命周期 Action ID 和显式 interaction Effect 测试，删除 Travel 特例断言。 |
| `test_time_conditions.py` | 保留 | 时间 predicate 和 path resolution 是通用查询机制。 | 保留。 |
| `test_world_manager_runtime.py` | 重写 | public runtime API、tick 推进、terminal 后停止有效；Creature compatibility projection 和当前 ReactionFailure 结构会固定领域政策及旧错误模型。 | 保留 runtime 行为，迁移 Creature snapshot 断言，统一 Failure 后重写 stop reason。 |
| `test_world_settlement.py` | 重写 | Reaction FIFO、child event context、失败 Reaction 停止和已提交前序 Bundle 都是关键行为；`ReactionApplied`/`triggered` 直接写 interaction，以及缺省 business 分类是明确错误规格。 | 删除这些 interaction 和缺省 kind 断言，以 committed Event、Action identity 和可选 narrative interaction 重建测试。 |
| `test_world_state_entity_perception.py` | 迁移/拆分 | 感知机制有价值；文件大量断言 Camping 实体、中文描述、Creature vitals 和具体 Recipe 名称，属于 world/capability package。 | 将 Camping 回归移动到 Package 测试；核心只保留通用可见性和 view 构造契约。 |

## 4. 明确应删除或替换的旧断言

以下项目不应继续作为生产代码必须满足的规格：

1. Reaction triggered/applied 必须直接出现在 `WorldState.interaction_log`；
2. 缺少错误性质时自动按 `business` 处理；
3. Diagnostics 将 `engine` 或 `contract` 有损归并为 `kernel`；
4. LLM 基础设施失败必须转换成合法 `noop`；
5. Workflow 从 `WorldState.services` 取得 diagnostics、interaction engine、
   workflow profile 或任意新增运行设施；
6. 命令只完成编译、尚未提交 Bundle 时已经存在 success interaction；
7. Creature、LowNutrition、Corpse 或 Camping Recipe 必须存在于核心 Catalog；
8. 历史研究数据的具体数量必须由默认内核单元测试保护。

删除这些断言前，应先写出对应的新契约测试。新测试可以保持红色，直到实现恢复；
不得通过恢复旧越权路径让测试转绿。

## 5. 建议执行批次

### 批次 1：建立恢复锚点

- 在 executor/settlement seam 增加：后续 Effect 失败时，前序世界修改、成功
  Event 和成功 Interaction 全部不可见；
- 增加 Workflow、Recipe、Reaction 不直接调用 `ws.record_event()` 或
  `ws.record_interaction_attempt()` 的边界测试；
- 暂不调整领域 package 测试。

### 批次 2：清除明确错误规格

- 重写 `test_world_settlement.py`；
- 删除 `test_diagnostics.py`，增加单次 Failure 报告和 EffectRecord 契约测试；
- 重写 `test_llm_ungroundable_replan.py` 与 `test_agent_workflow_runtime.py`；
- 统一 Failure 后更新所有旧 `kind`、`recoverable` 和 stop reason 断言。

### 批次 3：迁移领域测试

- Creature、LowNutrition、Camping perception 移到相应 capability/world package；
- 保留 package 未选择时定义不可见、选择后行为恢复的双向测试；
- 把研究数据完整性检查移出默认内核单元测试入口。

### 批次 4：整理公共 seam

- 用 Binder/Executor 公共接口替代直接 handler 和私有函数测试；
- 用显式 runtime interface 替代 `WorldState.services` 测试 fixture；
- 更新完整基线和文档中的测试职责说明。

## 6. 每批验收

每批修改必须满足：

- 被删除的测试有明确违反的内核不变量或替代测试；
- 新测试从已确认契约推导，不从当前实现反推；
- 不通过新增 `WorldState.services` key 让测试转绿；
- 不通过提前写 Event/Interaction 让测试转绿；
- 保留 executor transaction、Package isolation、catalog freeze、archive/checkpoint
  round-trip 的有效覆盖；
- 记录当批预期红灯、实际通过项和仍待实现的契约。
