# 社交平台 runtime 设计

## 目标与边界

本模块提供一个可独立运行的类微博社交平台，用于风险信息传播实验。它维护账号、关注网络、帖子、推荐流、曝光与互动事实；KERN 维护 tick、Agent 决策、EffectBundle 事务、事件和实验归档。

```text
scenario Package / KERN tick
-> social platform adapter
-> standalone SQLiteSocialPlatform
-> feed items, exposure and interaction facts
-> KERN events, reactions and experiment metrics
```

平台不判定事实真伪、不生成 Agent 决策、不直接修改 `WorldState`。它仅根据明确的输入提供确定性推荐和平台操作。

本文是当前社交平台子系统的设计依据。已删除的旧版
`social_platform_runtime_plan.md` 只用于追溯设计动机；其中的旧 effect、旧
workflow、旧 gate、组件 ID 和场景路径不构成兼容目标。

## 文档状态与使用方式

本文同时记录三类信息，避免把设计目标误读为现有能力：

- **已实现**：已有代码与聚焦测试覆盖的能力；代码和测试是最终依据。
- **已确认、未实现**：后续实现必须满足的契约和验收条件，不应假定运行时已经提供。
- **已知问题**：当前原型与已确认契约的差异；它们是清理和实现工作的输入。

本文是活跃设计文档，尚未冻结为稳定发布契约。研究材料和
`research_data/su7_social_platform_legacy/` 只提供输入或素材，不定义当前运行时行为。

## 已确认的需求

以下需求从旧版实验中保留，并按当前 KERN 边界重新实现：

1. 平台事实独立保存。账号、帖子、关注边、推荐、曝光和互动由外部 runtime
   管理；KERN 管理 Agent、tick、EffectBundle、events 和 archive。
2. 推荐、实际曝光和互动是三个独立事实。`recommend_feed` 不隐式写曝光，Agent
   只能操作已经呈现在自己终端上的帖子。
3. 手机实体上的 `social_propagation:ScreenComponent` 保存短期可操作页面。平台
   数据库仍是平台事实的唯一来源。
4. planner 表达语义意图，grounder 或领域 binder 从新鲜的屏幕页面解析卡片和
   `post_id`。planner 不依赖未展示候选或全局平台状态。
5. 所有平台写操作通过 Package effect 和 `external_runtime_bridge` 提交。Agent
   输出和 workflow 不直接写 SQLite 或 `WorldState`。
6. 每个 tick 的活跃 Agent 数、页面数和动作数都有显式上限。同一 tick 的推荐
   基于 tick 开始时的平台状态；本 tick 新提交的转发从下一 tick 开始传播。
7. 转发卡片和曝光记录保留原帖作者、直接传播者和来源类型，以支持多跳传播
   归因、首次触达来源和级联深度计算。
8. 外部 SQLite 写入加入 EffectBundle 生命周期。bundle 失败时回滚平台写入；
   KERN 与平台 checkpoint 使用相同 `run_id` 和 tick 恢复。
9. Agent 只接收自己的当前屏幕、静态身份和显式有界记忆。KERN event log 不
   自动进入 Agent 记忆。
10. 运行时保存原始传播事实。CSV、统计报告和图表由独立分析工具生成。

第一阶段研究闭环冻结为推荐、曝光和转发。点赞、评论、原创发帖、关注变更、
平台干预、PHEME 接入和 dashboard 不属于此阶段，不应为其预留兼容分支或暗含实现。

## Package 与外部 runtime 的归属

社交平台是 `SocialPropagation` Package 的运行依赖，不是运行者在入口 config 中为该
Package 手工拼装的可选功能。目标装配关系如下：

```text
runtime config selects Packages
-> Package declares required external-runtime instances
-> KERN resolves the Package-declared provider and options
-> KERN creates and starts each instance
-> run identity records the resolved instances
-> KERN closes them with the run
```

一个 Package 的声明同时指定 `runtime_id`、可信 `provider` 和可归档的纯 JSON
`options`。例如，`SocialPropagation` 声明 `social_platform` 实例使用
`social_propagation:sqlite_platform`。数据库运行路径、`run_id`、checkpoint 目录等
每次运行不同的值由 KERN runtime context 注入，不写死在 Package 数据中。

因此，完成迁移后入口 config 只选择 world Package、capability Packages 和通用运行
参数；它不再重复声明 `external_runtimes`。同一实例不能同时由 config 和 Package
声明，避免 provider、options、运行身份不一致。

## 已实现

以下能力已存在于当前工作树；它们构成原型基础，不等于完整社交传播场景。

### 外部 runtime 装配

- `ExternalRuntimeCatalog`：Package 用 `@package_external_runtime` 声明可信 provider；加载时注册并冻结。
- runtime config 支持 `external_runtimes` 实例声明：`runtime_id`、`provider` 和纯 JSON `options`。
- `KernRuntime.from_config()` 根据选中的 provider factory 创建 adapter，并调用 `start()`；调用方完成运行后调用 `runtime.close()`，adapter 收到 `close()`。
- checkpoint identity 包含已注册 provider 与选中的 runtime 实例配置。`options` 会写入运行身份，不能包含 API key、token 等秘密；秘密只能以环境变量引用名配置。
- `Packages/SocialPropagation` 已提供 `social_propagation:empty_platform`，用于验证 config、factory、start/close 和 bridge 接线。

上述是当前的显式 config 装配能力。Package 自主声明并自动启动实例是目标契约，尚未实现。

### 独立 SQLite 原型

`KERN.external_runtimes.social_platform.SQLiteSocialPlatform` 只依赖 Python 标准库，可被独立脚本直接使用。当前支持：

- 导入账号、兴趣权重、帖子、标签和关注关系；
- 确定性的 `recommend_feed(account_id, tick, limit)`；
- 显式 `record_exposure(...)`；
- 仅允许对已曝光帖子 `repost(...)`，且同一账号不能重复转发同一原帖；
- 查询累计曝光与累计转发；
- 将自身 SQLite 数据库保存和恢复为独立 checkpoint。

初版推荐只考虑帖子标签兴趣、是否关注原作者、帖子新鲜度与累计转发量。它不隐式写入曝光，便于区分“被算法推荐”与“实际被用户看到”。它是独立原型，尚未实现本文件定义的转发区、多跳归因或 EffectBundle 事务接线。

### 手机屏幕组件

`SocialPropagation` Package 已注册
`social_propagation:ScreenComponent`。它挂在手机、电脑等终端实体上，保存
当前 Agent 可以查看和操作的页面：

- `runtime_id`、`account_id`：显式绑定外部 runtime 实例和平台账号；
- `app`、`view`、`title`：当前应用和页面；
- `feed_items`、`current_post`、`selected_post_id`：当前可操作卡片；
- `cursor`、`updated_tick`：分页位置和页面新鲜度；
- `status_text`、`last_event_type`、`last_error`：最近一次平台操作的可见结果。

`runtime_id` 和 `account_id` 是模板必填字段。组件不保存关注图、全量帖子、推荐
分数、累计指标或其他账号画像。未来的推荐/打开 effect 在外部 runtime 操作成功
后更新此组件；平台写失败时屏幕状态与同一 bundle 一起回滚。

典型终端模板如下：

```json
{
  "name": "Social Phone",
  "components": {
    "TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
    "social_propagation:ScreenComponent": {
      "runtime_id": "social_platform",
      "account_id": "agent_023",
      "app": "social_platform",
      "view": "blank"
    }
  }
}
```

### 可用 legacy seed

`research_data/su7_social_platform_legacy/` 保留了可导入初始数据：

| 数据 | 数量 | 说明 |
|---|---:|---|
| agent 画像与 agent/account 映射 | 100 | 人格、社会属性与账号映射 |
| 平台账号 | 111 | 100 个普通 agent 账号与 11 个机构/种子账号 |
| 初始帖子 | 14 | 在 tick 0、1、2、3、4、5、7、8 投放 |
| 关注关系 | 1,900 | 已验证端点存在且无重复 |

它不包含历史曝光、点赞、评论或转发。SU7 文本仅作为 seed 数据格式的回归样本；海平面实验将使用新的帖子和条件 seed。

## 已确认、未实现

- `SQLiteSocialPlatform` 的 KERN adapter 与 Package effects；
- Package 声明 required external-runtime instance 并自动启动；
- 手机实体模板、屏幕读取 view 和更新屏幕的领域 effects；
- 点赞、评论；
- 推荐流中的转发卡片和转发关系传播；
- 外部 SQLite 写入与 EffectBundle 的 `external_transactional` 事务接线；
- KERN checkpoint 与外部 SQLite checkpoint 的正式恢复路径；
- 海平面“后果聚焦/解决方案聚焦”场景数据、Agent 决策函数、逐 tick 指标导出；
- 异步外部事件 polling。社交传播仿真第一版不需要此能力。

## 已知问题与清理边界

本节是对当前原型的审计结果。这里的差异不应通过兼容代码或静默降级掩盖；应按已确认契约直接重做相关数据模型、adapter 和测试。

### P0：当前路径不构成社交传播仿真

- runtime config 只装配 `social_propagation:empty_platform`；真实 SQLite 平台没有 KERN adapter、Package effect、binder、handler 或手机场景数据。
- 当前 smoke config 选择的是 Camping world Package，只验证 capability Package 与空 adapter 的装配和生命周期，不能证明社交推荐、曝光或转发行为。
- `KernRuntime.close()` 已存在，但 `default_orchestrator.py` 在运行结束后没有调用它。空 adapter 没有资源，因此该遗漏尚未暴露；真实 SQLite 或远程 adapter 接入前必须修复并测试关闭路径。

### P0：SQLite 原型的数据模型不足

- `exposures` 当前只有 `source`，缺少 `exposure_id`、`source_kind`、`source_account_id`、`section` 等已确认字段；无法保存转发触达的直接传播者和区块归因。
- 当前曝光唯一键是 `(account_id, post_id, tick)`，写入使用 `INSERT OR IGNORE`。它会静默丢弃同一 tick 的重复触达，与“每次真实页面呈现都是事实”的要求冲突。
- 当前 `reposts` 只记录账号、原帖和 tick；推荐查询不读取转发记录。因此 A 转发 P 后，关注 A 的 B 不会收到标记 A 为传播来源的卡片，不能形成多跳级联。

### P0：推荐与事务语义尚未达到契约

- 已曝光帖子当前仍按兴趣、关注、新鲜度和转发量计算分数；`previously_exposed` 只是返回字段。已确认契约要求其最终分数固定为 0，同时仍可在候选不足时重复展示。
- SQLite 原型按单次方法调用打开连接并提交，没有加入 KERN `external_transactional` 的 begin/commit/rollback 事务 API。一个失败的 EffectBundle 不能保证外部平台写入与世界状态一起回滚。
- 平台 checkpoint 能单独保存和恢复，但尚未实现 adapter lifecycle，也没有与 archive 的 `run_id`、tick 恢复路径进行端到端验证。

### P1：装配契约仍处于迁移状态

当前外部 runtime instance 由顶层 `external_runtimes` config 声明；Package 自主声明 required instance 并由 KERN 自动启动仍是未实现目标。迁移完成前，配置与 Package 之间的 provider/options 一致性只能依赖人工维护。

### P1：正式画像链路当前不可运行

`SocialProfileSampler._sample_specifics()` 调用了不存在的 `_specific_value_weights()`。因此画像生成器和 CLI 不能产生 profile，相关测试在该调用处失败。恢复该接口时还必须先处理年龄与教育类别的抽样顺序：18–24 岁样本不能先抽到无法生成有效具体学历的研究生类别。该链路属于第 6 步，不能随当前原型标记为已实现；修复后再恢复生成器和报告测试。

## 已确认的目标数据模型

`posts` 保存原始内容，`reposts` 保存账号对原帖的一次转发。转发不复制原帖文本为新的独立内容实体。

```text
Account --follows--> Account
Account --authors--> Post
Account --reposts--> Post
Account --likes--> Post
Account --comments--> Post
FeedExposure --presents--> Post
FeedExposure --source--> original author or reposter
```

建议表和关键字段如下：

| 表 | 关键字段 | 用途 |
|---|---|---|
| `accounts` | `account_id`, `display_name` | 账号 |
| `account_interests` | `account_id`, `tag`, `weight` | 推荐和决策画像输入 |
| `posts` | `post_id`, `author_id`, `text`, `created_tick` | 原始帖子 |
| `post_tags` | `post_id`, `tag` | 内容主题 |
| `follows` | `follower_id`, `followee_id` | 关注图 |
| `reposts` | `repost_id`, `account_id`, `post_id`, `created_tick`, `text` | 转发关系和可选转发语 |
| `likes` | `account_id`, `post_id`, `created_tick` | 每账号对原帖一次不可撤销的点赞 |
| `comments` | `comment_id`, `post_id`, `author_id`, `text`, `created_tick` | 评论 |
| `exposures` | `exposure_id`, `account_id`, `post_id`, `source_kind`, `source_account_id`, `tick`, `section`, `position`, `score` | 一次真实 feed 呈现，可保留重复触达 |

`reposts` 的唯一键应为 `(account_id, post_id)`：一个账号对一条原帖最多转发一次。被转发的原帖仍是唯一内容根，故累计转发量能够准确汇总，评论和点赞也不会分裂到重复副本。

## 转发进入推荐流

这是平台传播的核心规则。

当账号 A 转发原帖 P 后，任何关注 A 的账号 B 在后续 `recommend_feed(B, ...)` 中都会获得一个候选卡片。卡片必须保留 P 的原始作者和内容，同时明确 A 是传播来源：

```json
{
  "feed_item_kind": "repost",
  "post_id": "post_risk_001",
  "original_author_id": "earth_voice",
  "reposted_by_account_id": "agent_023",
  "reposted_tick": 4,
  "text": "原帖正文",
  "tags": ["climate_risk", "consequence"]
}
```

因此，B 的曝光记录应记为：`post_id=P`、`source_kind="followed_repost"`、`source_account_id=A`。B 若再次转发 P，B 的关注者又会在下一轮获得 `reposted_by_account_id=B` 的卡片，形成逐层扩散。

同一原帖在一页中至多出现一次。转发区先确定至多 3 个原帖；普通推荐区补位时排除这些 `post_id`。如果用户同时关注多个转发者，排序器选择得分最高的传播来源；可选地在卡片上显示其他已关注转发者数量。

## 推荐规则 v1

每个 Agent 在一个 tick 最多获得一页 8 张卡片。页面由两个独立区块组成：

1. **转发区**：从“我关注的账号已转发”的记录中选取，最多 3 张；
2. **普通推荐区**：从原帖候选中选取，补足页面到 8 张。

转发区候选不足 3 张时，普通推荐区补足所有空位；转发区候选超过 3 张时，仅保留排名前 3 张。转发区不挤占超过 3 个位置，因此普通推荐区始终至少有 5 个位置可用；若普通推荐区本身不足，页面可以少于 8 张。

在 tick `t`，候选来源包括：

1. 原作者直接发布的原帖；
2. 用户关注账号的转发记录，每一条构成“被关注者转发”的候选来源。

对候选来源计算确定性分数：

```text
score =
  2.0 × tag_interest_match
+ 1.5 × source_follow_boost
+ 1.0 / (1 + source_age_ticks)
+ 0.5 × engagement_signal
```

- `tag_interest_match`：帖子标签与用户兴趣权重之和；
- `source_follow_boost`：直接关注原作者或转发者时为 1；普通推荐区的原作者不受关注时为 0；
- `source_age_ticks`：原帖发布时间或转发发生时间到当前 tick 的间隔；
- `engagement_signal`：原帖的转发、点赞与评论的单调聚合；

已曝光不作硬过滤。若账号 B 此前已经曝光过原帖 P，P 仍可作为普通推荐或转发区的候选，但该候选的最终 `score` 固定为 `0`，不再叠加兴趣、关注、新鲜度或互动信号。它会排在所有正分候选之后；候选不足时仍可再次展示。这允许记录“原作者首次触达”之后的“关注者转发重复触达”。

每张实际显示的卡片都写入一条曝光记录，包括 `source_kind`、`source_account_id`、区块和位置。首次曝光来源由该账号、原帖的最早曝光记录得出，而不是覆盖后续重复触达。

排序按 `score` 降序，再按稳定字段排序。第一版不使用随机探索，以确保同一 seed、同一网络、同一 Agent 决策与同一 tick 得到相同结果。后续若加入探索，随机源必须由实验 seed 派生并记录。

## 平台操作契约

独立引擎的 Python API 与 KERN adapter 操作一一对应：

| adapter operation | 独立引擎方法 | 成功事件 |
|---|---|---|
| `recommend_feed` | `recommend_feed` | `SocialFeedRecommended` |
| `record_exposure` | `record_exposure` | `SocialPostExposed` |
| `repost` | `repost` | `SocialPostReposted` |
| `like` | `like` | `SocialPostLiked` |
| `comment` | `comment` | `SocialCommentCreated` |
| `metrics` | `metrics` | `SocialMetricsObserved` |

每个写操作都必须验证账号、原帖、操作前提和幂等性。`repost` 必须验证此前曝光；`like` 与 `repost` 重复执行应被拒绝；点赞不提供取消操作；评论正文不可为空。

## KERN 事务与检查点

Package effect 通过 `ws.services["external_runtime_bridge"]` 调用命名 adapter。`record_exposure`、`repost`、`like`、`comment` 都声明为 `external_transactional`：

```text
EffectBundle begins
-> adapter receives external_transaction_id
-> SQLite runtime begins/joins that transaction
-> all platform writes succeed: commit_bundle commits it
-> any world/effect failure: rollback_bundle rolls it back
```

`recommend_feed` 与 `metrics` 是只读操作。外部 runtime checkpoint 应在 KERN 每次 archive 记录后保存自己的 SQLite snapshot；恢复时按 archive 的 `run_id` 和 `tick` 恢复同一份外部 snapshot。两边不能实现跨文件原子提交，外部 checkpoint 失败仍视为运行失败。

## 逐 tick 仿真循环

一个 tick 使用开始时冻结的平台状态构造所有已调度 Agent 的页面。这样，同一 tick 中先后执行的 Agent 不会因为执行顺序而看见彼此刚完成的转发；本 tick 提交的转发从下一 tick 才成为关注者的转发区候选。

```text
1. tick t 开始：载入本 tick 的计划投放帖子，确定活跃账号。
2. 推荐快照：平台从 tick 开始状态，为每个活跃账号生成 8 张卡片。
3. Agent 感知：Agent 只接收自己的页面、静态身份与自己的有界记忆。
4. Agent 决策：对实际看到的卡片选择不操作、转发或后续已启用的互动。
5. EffectBundle：先记录本页全部曝光，再执行该 Agent 选择的写操作。
6. 事务提交：WorldExecutor 与 external runtime 一起提交；失败则整个 bundle 回滚。
7. 结算与归档：提交后的事件才触发 reactions；采样本 tick 指标并保存 KERN 与 SQLite checkpoint。
8. tick t + 1：已提交的转发成为关注者的转发区候选。
```

### Agent 可见信息与记忆

Agent 的决策输入应限制为与真实平台用户相称的信息：

- 静态身份：结构化社会属性、人格、兴趣、媒介使用偏好，以及从这些字段生成的角色背景；
- 当前页面：至多 8 张可见卡片的正文、标签、原作者、发布时间；转发卡片另含转发者及转发时间；
- 自己的有界历史：近期看过、转发过或互动过的帖子摘要，以及运行中明确写入的个人记忆；
- 与当前决策直接相关的公开卡片信号，例如显示给用户的互动计数。

Agent 不应看见平台排序分数、全网关注图、其他账号的私有画像、全局累计指标、未展示候选或 KERN 的内部事件日志。事件日志用于审计与 reactions，不自动成为 Agent 记忆。需要跨 tick 保留的个人认识或行为后果，必须由显式 memory effect 写入一个有界摘要。

当前屏幕是短期操作上下文，不是长期记忆。执行动作前必须检查屏幕属于当前
Agent 绑定的账号，且 `updated_tick` 落在场景声明的新鲜窗口内。屏幕过期时需要
重新获取 feed，不能从 Agent 记忆中的旧 `post_id` 直接执行平台写操作。

### 画像生成链路

正式画像链路固定为一条：

```text
deterministic structured sampler
-> validated structured profiles.json
-> distribution and contract report
-> LLM natural-language background generation
-> scenario agent/account composition
```

结构化采样负责年龄、教育、职业、家庭、经济状态、平台偏好、兴趣和人格之间的
一致性。LLM 只把已经验证的结构化画像改写成自然语言，不修复字段、不增加高风险
事实。`research_data/su7_social_platform_legacy/profiles.json` 只作为旧数据回归样本，
不作为正式生成工具的默认输入。画像、账号、关注网络和自然语言背景都要记录同一
实验 seed 与生成版本。

正式工具的默认产物路径统一为：

```text
KERN/external_runtimes/social_profiles/generated_social_profiles.json
KERN/external_runtimes/social_profiles/generated_social_agent_backgrounds.jsonl
```

该目录已被 `.gitignore` 排除，生成物可以按 seed 重新生成。使用 legacy 画像必须
显式传入 `--profiles`，避免旧数据意外进入新实验。

### 为什么这是传播机制的近似

该模型不把单个 Agent 的输出解释为真实用户行为的证明。它近似的是一个可审计的机制：异质身份影响条件化决策；关注边约束谁能获得社交转发触达；确定性推荐决定可见性；曝光、转发和时间顺序决定后续可达性。相同的 seed、网络、页面规则与决策策略会产生可复跑的传播轨迹，改变叙事、网络或决策策略则可比较机制差异。

这种近似的有效性取决于画像、决策策略、网络和推荐规则是否针对研究问题校准，并需通过多 seed 与网络条件检验稳健性。它可以回答“在已定义机制下会发生什么”，不能直接外推为真实平台的总体因果结论。

## 实施顺序与验收

1. 已完成：注册 namespaced `ScreenComponent`，验证 Package catalog 序列化往返；实现独立 SQLite 原型的基础推荐、曝光、转发和 checkpoint。
2. 重做独立 SQLite 数据模型和推荐：实现转发区、来源字段、重复曝光的 0 分规则和固定 8 卡页面。
3. 为独立引擎添加 SQLite 事务 API，并测试失败回滚。
4. 将 `social_propagation:empty_platform` 换成 `social_propagation:sqlite_platform` adapter；Package required instance 的自动装配另行完成。
5. 增加手机实体模板和 Package effects：推荐、曝光、转发、屏幕更新和逐 tick 指标采样。
6. 接入唯一画像链路，编写海平面场景 seed、异质 Agent 决策与实验运行/CSV/折线图工具。

核心验收：

- 每个推荐页最多 8 张卡片，转发区最多 3 张，不足位置由普通推荐补足；
- A 转发 P 后，关注 A 的 B 在下一 tick 转发区可看到一张明确标注“A 转发”的 P 卡片；
- B 的曝光记录保留 `source_account_id=A`；
- B 转发后，B 的关注者可继续收到该传播链；
- 已曝光的 P 再次出现时分数为 0，但仍留下新的、带来源的曝光记录；
- 点赞、评论、转发计数准确且重复操作受约束；
- 屏幕只包含当前账号实际展示的卡片，过期页面不能提供可执行 `post_id`；
- 手机组件通过 build、archive 和 checkpoint 使用同一 runtime-scoped catalog 往返；
- 一个失败的 KERN bundle 不会留下外部 SQLite 部分互动；
- 使用同一实验 seed 重跑，feed、曝光与累计转发曲线一致。

当前聚焦测试只覆盖 SQLite 原型的基础推荐/曝光/转发、独立 checkpoint、legacy seed 导入，和 `ScreenComponent` 的 catalog 往返。上述核心验收尚未覆盖，必须随第 2–5 步逐项新增行为测试。
