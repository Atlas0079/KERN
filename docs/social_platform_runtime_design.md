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

本文描述当前工作树已经采用的社交平台实现与海平面两条件实验契约。代码和聚焦测试仍是
最终依据；本文用于说明设计边界、数据契约、已实现能力和剩余验收工作。

研究材料和 `research_data/su7_social_platform_legacy/` 只提供输入或素材，不定义当前运行时
行为。旧版 schema、旧 effect、旧 workflow、旧 gate、旧组件 ID 和旧场景路径不构成兼容目标。

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

第一阶段平台行为闭环冻结为推荐、曝光、转发、点赞和扁平评论。研究的主要结果变量
仍是转发；点赞和评论用于构成完整的可选平台行为及 Agent 决策环境。评论直接属于
原帖，不是帖子，也没有父评论或回复关系。原创发帖、关注变更、平台干预、PHEME
接入和 dashboard 不属于此阶段，不应为其预留兼容分支或暗含实现。

## 海平面两条件实验契约

正式实验只比较 `sea_level_consequence_focus`（后果聚焦）与
`sea_level_solution_focus`（解决方案聚焦）。两个条件分别独立运行，共用同一批
300 个 Agent、同一关注网络、同一活跃调度随机数、同一推荐参数和同一组背景帖子，
每轮只投放一篇实验帖。实验帖共用相同的海平面与气候风险推荐标签；
`consequence_focus` 和 `solution_focus` 只作为实验元数据，不参与推荐分数。

以下为场景生成器与社交 workflow 当前实现采用的冻结默认值：

### 账号与关注网络

- 每个 Agent 对应一个普通平台账号；姓名不是实验变量，账号使用稳定的
  `account_001` 等 ID。另建一个发布实验帖的机构账号 `earth_voice`。
- 网络由实验 seed 确定性生成，不从自然语言背景反推未采样的媒介偏好。
- 普通账号目标出度限制在 8–32，群体平均约为 19–20。外向性只对目标出度提供
  温和正向修正，不直接决定关注对象。
- 关注对象的抽样分数组合四类机制：目标账号的重尾受欢迎度、明确兴趣主题相似度、
  生命周期相近程度和三角闭包。受欢迎度制造少数中心节点，主题与生命周期产生同质性，
  三角闭包形成局部社群。
- `earth_voice` 获得一小组由 seed 固定的初始关注者，其余触达来自普通推荐和后续
  转发。场景同时提供两条件共用的中性背景帖子，使实验帖需要竞争有限推荐位。
- 生成后必须验证无自关注、无重复边、端点存在，并报告入度/出度分布、最大弱连通分量、
  聚类程度和机构账号初始关注者数量。

当前 300 Agent 生成器使用平均目标出度约 20、`earth_voice` 初始关注者 24 人和 40 条两条件
共用的中性背景帖。这些值写入 `Study/study_config.v1.json`、生成 manifest 和平台 seed；
pilot 后如需校准，应修改 study config 并重新生成 disposable 数据。

### 推荐近似

采用可解释的类微博双通道近似，不声称复刻任何商业平台的私有算法：

1. 关注传播区最多 3 张卡片，候选来自我所关注账号在此前 tick 的转发；
2. 普通推荐区补足页面至最多 8 张，候选来自帖子主题兴趣、是否关注作者、新鲜度和
   此前 tick 的累计转发量；
3. 同一页内同一原帖只出现一次，已曝光帖子可重复出现但得分固定为 0；
4. 点赞和评论数量作为公开信号显示，但第一版不参与排名；
5. 同一 tick 的所有推荐只读取 tick 开始前已经存在的互动事实。

账号推荐兴趣只映射结构化画像中明确采样的科学主题和兴趣事实。没有相关事实的账号
保留低权重通用知识主题，不补写“媒介偏好”“互动风格”或立场字段。

### 传播轮次与访问计划

tick 不映射分钟、小时或自然日。一个 tick 表示一次离散的传播机会轮次：本轮选中的
Agent 各打开一次平台，获得一页推荐并对实际曝光内容作出决策；本轮提交的转发从下一轮
开始成为新的候选传播来源。图表横轴统一写作“传播轮次（tick）”，结果不得解释为现实中
经过了多少小时。

平台推荐算法不决定 Agent 何时打开平台。实验使用独立的 `SocialActivityScheduler` 在运行
前生成完整访问计划；LLM 不参与上线判断。第一版也不加入通知触发，因为通知会让不同实验
条件产生不同访问计划，混淆叙事处理与注意力供给。

访问计划采用有个体异质性的离散更新过程。每次访问后，为 Agent 抽取距离下一次访问的轮次
间隔：

```text
log_gap(i, k) = gap_intercept
              - 0.70 * (extraversion_i - 0.5)
              - 0.20 * (openness_i - 0.5)
              - 0.10 * (conscientiousness_i - 0.5)
              - 0.05 * (neuroticism_i - 0.5)
              + 0.00 * (agreeableness_i - 0.5)
              + individual_random_intercept_i
              + gap_noise(i, k)

gap(i, k) = max(1, round(exp(log_gap(i, k))))
next_open_tick(i, k) = current_open_tick(i, k) + gap(i, k)
```

外向性承担主要人格效应；开放性和尽责性只提供较小修正；神经质只表示很弱的信息警觉；
宜人性不用于解释是否上线，主要留给看帖后的情境决策。`individual_random_intercept_i` 是由
study seed 派生且对单个 Agent 固定的无语义异质性，`gap_noise(i, k)` 表示工作、通勤、休息、
临时空闲等未观测生活因素。二者都不写入人物画像，也不进入 LLM 提示词。

所有随机量从 `study_seed`、`agent_id` 和访问序号派生。两个实验条件必须读取同一份完整
activation schedule，而不是分别重新抽样。调度器输出每个 Agent 的全部访问轮次和生成审计，
作为运行输入保留。

当前 300 Agent 配置使用固定 100 个传播轮次，目标为每轮平均约 12% 的 Agent 打开平台。
每轮 60 人只作为安全阈值；若生成计划超过阈值，生成失败并重新校准分布参数，不能在运行时
截断活跃 Agent。正式比较可另做低、中、高三种访问强度的敏感性分析，例如目标活跃比例
8%、12% 和 20%，每一强度下两条件仍共享访问计划。

没有目标平台访问日志时，这一机制称为“具有个体异质性和间歇性的随机注意力模型”，不称为
真实平台登录行为拟合。若以后获得日志，只按群体层面的每轮活跃比例、相邻访问间隔分布、
至少访问一次的账号比例和个体频率方差校准参数，不为单次上线编造具体生活原因。

### 社交专用 workflow

社交实验使用单独注册的 `AgentWorkflow`。一次激活先刷新一页并记录真实曝光；只有实验帖
实际出现在页面时才调用 LLM。LLM 只接收 Agent 的结构化人格、第一人称背景、当前公开卡片、
来源与公开互动计数、自己的有界记忆，并返回 `no_action` 或点赞、评论、转发的任意合理组合。
评论正文随决策返回。提交后的结果才写入个人记忆；KERN event log 不直接进入提示词。

社交 workflow、活跃调度、兴趣映射、过程留痕和剩余验收工作详见
`social_platform_experiment_plan.md`。

## Package 与外部 runtime 的归属

当前实验由顶层 runtime config 显式声明 `social_platform` 实例、provider 和纯 JSON
options。选择 `SocialPropagation` Package 注册可信 provider、effect、component 和 recipes；
实验 config 负责选择其中的 `social_propagation:sqlite_platform` provider。

```text
runtime config selects Packages and external-runtime instances
-> selected Package registers trusted providers
-> KERN resolves the config-selected provider and options
-> KERN creates and starts each instance
-> run identity records the resolved instances
-> KERN closes them with the run
```

实验 config 声明 `runtime_id="social_platform"`、可信 provider 和可归档的纯 JSON
`options`。数据库运行路径、`run_id`、checkpoint 目录等每次运行不同的值由 KERN runtime
context 注入。Package 自主声明 runtime 不进入当前实验里程碑。

## 已实现

以下能力已存在于当前工作树，构成海平面社交传播实验的运行基础。

### 外部 runtime 装配

- `ExternalRuntimeCatalog`：Package 用 `@package_external_runtime` 声明可信 provider；加载时注册并冻结。
- runtime config 支持 `external_runtimes` 实例声明：`runtime_id`、`provider` 和纯 JSON `options`。
- `KernRuntime.from_config()` 根据选中的 provider factory 创建 adapter，并调用 `start()`；调用方完成运行后调用 `runtime.close()`，adapter 收到 `close()`。
- checkpoint identity 包含已注册 provider 与选中的 runtime 实例配置。`options` 会写入运行身份，不能包含 API key、token 等秘密；秘密只能以环境变量引用名配置。
- `Packages/SocialPropagation` 提供 `social_propagation:empty_platform` 测试 provider 和可运行的
  `social_propagation:sqlite_platform` provider。后者包装独立 SQLite 引擎并实现 operation、
  Bundle 事务、checkpoint 和 close lifecycle。

上述显式 config 装配是当前实验采用的正式方式。

### 独立 SQLite 原型

`KERN.external_runtimes.social_platform.SQLiteSocialPlatform` 只依赖 Python 标准库，可被独立脚本直接使用。当前支持：

- 导入账号、兴趣权重、帖子内部主题、可见 hashtag、条件元数据和关注关系；
- 确定性的两段式 `recommend_feed(account_id, tick, limit)`：每页最多 8 张，其中关注者转发区最多 3 张；
- 转发卡片保留原作者、直接转发者、转发 tick、来源类型和区块；本 tick 转发从下一 tick 才进入推荐及互动计数；
- `open_feed_session(...)` 在一个事务中保存页面会话和全部曝光；空页面也保存会话，每次呈现生成独立 `exposure_id`；
- 点赞、评论和转发必须提交当前卡片的 `source_exposure_id`，并保存该精确归因；
- 同一账号不能重复转发或点赞同一原帖；评论可以有多条；
- 已曝光原帖仍可再次推荐，但分数固定为 0；
- `begin_transaction(...)`、`commit_transaction(...)` 和 `rollback_transaction(...)` 覆盖曝光与转发写入；
- 查询页面会话、曝光、点赞、评论、转发和累计指标；
- 将自身 SQLite 数据库保存和恢复为独立 checkpoint。

初版推荐只考虑帖子内部主题兴趣、是否关注原作者或直接转发者、来源新鲜度与此前 tick 的累计转发量。`recommend_feed` 保持只读；只有 `open_feed_session` 表示页面实际打开并写入曝光。独立引擎已经具备多跳传播和 SQLite 事务；KERN adapter 已将这些写入接到 EffectBundle lifecycle。

数据库 schema 固定为 `social_platform.v3`。旧 SQLite 文件和旧 checkpoint 是可重建生成物，运行时会拒绝旧 schema，不提供迁移或格式探测。

### 手机屏幕组件

`SocialPropagation` Package 已注册
`social_propagation:ScreenComponent`。它挂在手机、电脑等终端实体上，保存
当前 Agent 可以查看和操作的页面：

- `runtime_id`、`account_id`：显式绑定外部 runtime 实例和平台账号；
- `app`、`view`、`title`：当前应用和页面；
- `feed_items`、`current_post`、`selected_post_id`：当前可操作卡片；
- `feed_session_id`、`cursor`、`updated_tick`：已提交页面会话、分页位置和页面新鲜度；
- `status_text`、`last_event_type`、`last_error`：最近一次平台操作的可见结果。

`runtime_id` 和 `account_id` 是模板必填字段。组件不保存关注图、全量帖子、推荐
分数、累计指标或其他账号画像。浏览 effect 在外部 runtime 操作成功后更新此组件；
平台写失败时屏幕状态与同一 bundle 一起回滚。

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

### Legacy 素材

`research_data/su7_social_platform_legacy/` 保留旧实验素材：

| 数据 | 数量 | 说明 |
|---|---:|---|
| agent 画像与 agent/account 映射 | 100 | 人格、社会属性与账号映射 |
| 平台账号 | 111 | 100 个普通 agent 账号与 11 个机构/种子账号 |
| 初始帖子 | 14 | 在 tick 0、1、2、3、4、5、7、8 投放 |
| 关注关系 | 1,900 | 已验证端点存在且无重复 |

它不包含历史曝光、点赞、评论或转发，其帖子仍使用已退役的 `tags` 字段，不能直接导入
`social_platform.v3`。海平面场景生成器必须生成新的严格 seed；不在 runtime 中提供 legacy
转换或兼容读取。

### 海平面实验 Package 与运行配置

`Packages/SeaLevelSocialExperiment` 已提供当前海平面两条件实验 world Package：

- 300 个实验 Agent、300 个手机实体和 300 个普通平台账号一一绑定；
- `sea_level_social_experiment:SocialIdentityComponent` 保存 `profile_id`、第一人称背景和大五人格；
- `AgentControlComponent.provider_id="social_platform"` 选择内置社交 workflow；
- `AgentWakePolicyComponent` 使用 `NoActiveTask`，每轮是否打开平台由 workflow 读取 activation schedule 判断；
- `Data/Study/activation_schedule.json` 保存 100 tick 完整访问计划和 fingerprint；
- `Data/Study/actor_bindings.json` 保存 Agent、手机、账号、runtime 绑定；
- `Data/Platform/social_seed.sea_level_consequence_focus.json` 与
  `Data/Platform/social_seed.sea_level_solution_focus.json` 保存两条件 SQLite seed。

顶层运行配置已经组合 world Package、`SocialPropagation` capability Package、SQLite adapter
和内置 `social_platform` workflow：

- `runtime_config.sea_level.consequence.json`
- `runtime_config.sea_level.solution.json`

两份配置共享同一 world、网络、activation schedule、背景帖和 workflow；差异只在平台 seed、
SQLite 路径和 checkpoint 路径。

### 过程导出

`tools/export_social_platform_process.py` 已支持从 `social_platform.v3` SQLite 数据库导出原始过程
数据：全量平台表 CSV、`exposure_process.csv`、`repost_process.csv`、`summary_by_tick.csv`
和导出 manifest。导出器保留原始事实与基础派生字段，不在运行时固化最终统计解释。

## 剩余范围

- 10 Agent pilot、300 Agent smoke、同 seed 完整复跑和两条件运行级 schedule 相等测试仍待补齐。
- 最终指标口径、统计报告和图表生成脚本仍待在过程状态稳定后定义。
- 异步外部事件 polling 不属于第一阶段社交传播仿真。

### 正式画像结构化链路

画像生成器使用 `social_profile.v4`。生命周期使用确定性配额，性别作为可配置人口维度生成；精确年龄在教育、职业、家庭等依赖字段之前确定。教育按阶段生成专业轨迹，并将硕士与博士作为独立层级。每一步先建立满足硬约束的候选域，再应用带 `rule_id` 的软权重。空候选域和任何验证错误都会终止生成，不能通过重试、回退或 LLM 修复。

## 数据模型契约

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

第一阶段所需平台表均已实现：

| 表 | 状态 | 关键字段 | 用途 |
|---|---|---|---|
| `accounts` | 已实现 | `account_id`, `display_name` | 账号 |
| `account_interests` | 已实现 | `account_id`, `topic`, `weight` | 推荐主题权重 |
| `posts` | 已实现 | `post_id`, `author_id`, `text`, `condition_id`, `created_tick` | 原始帖子与实验元数据 |
| `post_ranking_topics` | 已实现 | `post_id`, `topic` | 内部推荐主题，不进入 Agent 感知 |
| `post_display_hashtags` | 已实现 | `post_id`, `position`, `hashtag` | 页面可见 hashtag |
| `follows` | 已实现 | `follower_id`, `followee_id` | 关注图 |
| `feed_sessions` | 已实现 | `feed_session_id`, `account_id`, `tick`, `page_limit`, `item_count` | 每次实际页面打开，包括空页面 |
| `exposures` | 已实现 | `exposure_id`, `feed_session_id`, `account_id`, `post_id`, source 与页面快照字段 | 一次真实卡片呈现，可保留重复触达 |
| `reposts` | 已实现 | `repost_id`, `account_id`, `post_id`, `source_exposure_id`, `created_tick`, `text` | 转发关系、附言和触发曝光 |
| `likes` | 已实现 | `account_id`, `post_id`, `source_exposure_id`, `created_tick` | 不可撤销点赞及触发曝光 |
| `comments` | 已实现 | `comment_id`, `post_id`, `author_id`, `source_exposure_id`, `text`, `created_tick` | 扁平评论及触发曝光；没有回复字段 |

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
  "display_hashtags": ["气候危机", "海平面上升"]
}
```

因此，B 的曝光记录应记为：`post_id=P`、`source_kind="followed_repost"`、`source_account_id=A`。B 若再次转发 P，B 的关注者又会在下一轮获得 `reposted_by_account_id=B` 的卡片，形成逐层扩散。

同一原帖在一页中至多出现一次。默认推荐策略会在关注者转发、兴趣匹配、高热度和探索随机候选之间动态选择；若同一原帖同时存在原帖候选和转发候选，最终页面只保留一个来源。如果用户同时关注多个转发者，排序器选择得分最高的传播来源；可选地在卡片上显示其他已关注转发者数量。

## 推荐规则 v2

每个 Agent 在一个 tick 最多获得一页 8 张卡片。平台先生成候选集合，再交给可替换的推荐策略选出页面。当前默认策略是 `HybridFeedRecommender`，它不是固定比例分栏，而是在每个位置动态比较以下候选通道：

1. **关注者转发**：从“我关注的账号已转发”的记录中选取，最多 3 张；
2. **兴趣匹配**：帖子内部 `ranking_topics` 与用户兴趣画像匹配，或原作者是用户关注账号；
3. **高热度**：此前 tick 已产生点赞、评论或转发的原帖；
4. **探索随机**：从未选中的原帖中做确定性探索，优先给未曝光、非纯兴趣匹配的内容一些进入页面的机会。

这些通道没有固定占比。默认策略会依据候选强度、当前页里同通道已出现次数、是否已曝光、以及账号/tick/页大小派生出的确定性扰动来选下一个位置。转发仍保留最多 3 张的上限，高热度也限制在最多 3 张；其余位置由当页实际候选竞争产生。若候选不足，页面可以少于 8 张。

在 tick `t`，候选来源包括：

1. 原作者直接发布的原帖；
2. 用户关注账号的转发记录，每一条构成“被关注者转发”的候选来源。

候选卡片仍计算一个基础确定性分数，供兴趣、转发和兜底排序使用：

```text
score =
  2.0 × topic_interest_match
+ 1.5 × source_follow_boost
+ 1.0 / (1 + source_age_ticks)
+ 0.5 × engagement_signal
```

- `topic_interest_match`：帖子内部 `ranking_topics` 与用户兴趣权重之和；
- `source_follow_boost`：直接关注原作者或转发者时为 1；普通推荐区的原作者不受关注时为 0；
- `source_age_ticks`：原帖发布时间或转发发生时间到当前 tick 的间隔；
- `engagement_signal`：基础分数只使用此前 tick 的累计转发量；高热度通道另行综合此前 tick 的转发、评论和点赞计数；

已曝光不作硬过滤。若账号 B 此前已经曝光过原帖 P，P 仍可作为普通推荐或转发区的候选，但该候选的最终 `score` 固定为 `0`，不再叠加兴趣、关注、新鲜度或互动信号。它会排在所有正分候选之后；候选不足时仍可再次展示。这允许记录“原作者首次触达”之后的“关注者转发重复触达”。

每张实际显示的卡片都写入一条曝光记录，包括 `source_kind`、`source_account_id`、区块和位置。首次曝光来源由该账号、原帖的最早曝光记录得出，而不是覆盖后续重复触达。

默认 hybrid 策略的探索不是运行时随机数，而是由策略版本、账号、tick、页大小和帖子 ID 派生出的稳定扰动。因此同一数据库、同一账号、同一 tick 和同一 limit 会得到相同页面；换账号、换 tick 或换候选池时，探索结果会随之变化。

## 平台操作契约

独立引擎的 Python API 与 KERN adapter 操作一一对应：

| adapter operation | 状态 | 独立引擎方法 | 成功事件 |
|---|---|---|---|
| `recommend_feed` | 已实现 | `recommend_feed` | `SocialFeedRecommended` |
| `open_feed_session` | 已实现 | `open_feed_session` | `SocialFeedOpened`、`SocialPostExposed` |
| `repost` | 已实现 | `repost` | `SocialPostReposted` |
| `metrics` | 已实现 | `metrics` | `SocialMetricsObserved` |
| `like` | 已实现 | `like` | `SocialPostLiked` |
| `comment` | 已实现 | `comment` | `SocialCommentCreated` |

每个写操作都必须验证账号、原帖、当前 tick 的精确 `source_exposure_id` 和幂等性。`like` 与 `repost` 重复执行应被拒绝；点赞不提供取消操作；评论正文不可为空。

## KERN 事务与检查点

Package effect 通过 `ws.services["external_runtime_bridge"]` 调用命名 adapter。`open_feed_session`、`repost`、`like`、`comment` 都声明为 `external_transactional`：

```text
EffectBundle begins
-> adapter receives external_transaction_id
-> SQLite runtime begins/joins that transaction
-> all platform writes succeed: commit_bundle commits it
-> any world/effect failure: rollback_bundle rolls it back
```

`recommend_feed` 与 `metrics` 是只读操作。外部 runtime checkpoint 应在 KERN 每次 archive 记录后保存自己的 SQLite snapshot；恢复时按 archive 的 `run_id` 和 `tick` 恢复同一份外部 snapshot。两边不能实现跨文件原子提交，外部 checkpoint 失败仍视为运行失败。

独立引擎一次仅允许一个活动写事务。SQLite Package adapter 在第一个平台写操作时加入
`external_transaction_id`，并通过 `commit_bundle` / `rollback_bundle` 完成同一事务；checkpoint
保存与恢复会拒绝未结束事务。聚焦测试验证平台写入与 `ScreenComponent` 在失败时一起回滚。

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

- 静态身份：结构化社会属性、人格、兴趣，以及从这些字段生成的角色背景；
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
versioned population config
-> deterministic lifecycle quotas
-> constraint-aware structured sampler
-> per-profile and population release gate
-> validated social_profile.v4 profiles.json
-> distribution and contract report
-> grounded LLM natural-language rendering
-> scenario agent/account composition
```

结构化画像中的事实只有一份：`demographics`、`education`、`occupation`、
`household`、`socioeconomic`、`personality` 和 `interests`。
年龄段、标签和摘要是这些事实的确定性投影，不能独立采样。生命周期是人口学依赖的
第一主轴；精确年龄约束已完成教育，教育和生命周期约束职业，年龄和生命周期约束家庭。
`education.history` 保存已完成的逐阶段教育轨迹。硕士包含本科与硕士阶段，博士包含本科、
硕士与博士阶段；每一阶段分别记录专业领域。同专业延续、相关转专业和跨领域转专业的概率
由配置决定，最终学历描述由轨迹末段确定性生成，不再额外抽样。

硬约束定义不允许进入正式样本的组合；软规则只调整少见但可行组合的相对权重，并在
可选 audit 中记录候选权重、选择值、规则 ID 和原因。100 人默认样本对生命周期使用最大
余数法配额，其余字段进行条件抽样。所有画像随机维度由
`social_profile_generation.v3` JSON 配置。完整默认配置定义生命周期年龄范围、性别、各分类维度
的权重与允许值、条件化规则、人格分布参数、兴趣数量与条目权重；特定群体配置通过显式
`extends` 继承并覆盖。`science_video` 是一份继承配置。代码只保留跨字段硬约束和确定性
采样算法。正式产物嵌入解析后的完整配置及其 SHA-256。

LLM 接收 `social_profile_source_card.v5`，以结构化事实为人物骨架生成第一人称自然语言背景。
每个采样元素拆为独立原子 fact，并要求正文逐项表达和回传完整 `covered_fact_ids`。研究口径允许
模型添加合理、低影响、与 source card 一致的衔接性细节；
这些扩写不成为正式实验变量，结构化画像仍是身份事实的权威来源。额外 JSON 字段作为审查信息
保留，不影响下游读取正式输出字段。媒介选择、信息倾向和互动风格仍由 Agent 在具体页面、
帖子、公开信号和有界记忆下逐次决策，运行后再从曝光与操作日志计算。

姓名不是实验变量，也不是自然语言输出契约的一部分；生成器不要求、校验或依赖姓名。
结构化字段为合并或模糊类别时，LLM 可以为单个人物选择一种确定解释并保持全文一致。
`logic_issue_explanation` 通常为 `null`；只有事实互相排斥或无法同时成立时才填写，并在正文中
尽可能提供自洽情境。罕见、非典型或职业与专业不一致等可能人生经历不标记为逻辑错误。
`research_data/su7_social_platform_legacy/profiles.json` 只作为旧数据素材，不作为正式生成工具
的默认输入。画像、账号、关注网络和自然语言背景都要记录同一实验 seed 与生成版本。

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

## 实施状态与验收

1. 已完成：注册 namespaced `ScreenComponent`，验证 Package catalog 序列化往返。
2. 已完成：重做独立 SQLite 数据模型和推荐，实现可替换 hybrid 推荐策略、来源字段、重复曝光的 0 分规则和最多 8 卡页面。
3. 已完成：为独立引擎添加 SQLite 事务 API，并测试提交、失败回滚、事务 ID 和 checkpoint 边界。
4. 已完成：增加 `social_propagation:sqlite_platform` adapter、Package effects 和 recipes，支持浏览、曝光、转发、点赞、扁平评论和指标采样；实验通过顶层 config 显式选择 runtime instance。
5. 已完成：在海平面 world Package 中生成 300 个实验 Agent、手机实例、身份组件和 actor/platform 绑定。
6. 已完成：实现唯一画像生成、验证、报告、grounded background 链路、海平面场景 seed、
   画像到 Agent/account 的组合、内置社交 workflow 和原始过程 CSV 导出器。
7. 待完成：pilot、300 Agent smoke、同 seed 完整复跑、两条件 schedule 相等测试，以及最终统计口径和图表工具。

第一阶段核心验收：

- 每个推荐页最多 8 张卡片，关注者转发最多 3 张，默认策略可动态混入兴趣匹配、高热度和探索随机原帖；
- A 转发 P 后，关注 A 的 B 在下一 tick 转发区可看到一张明确标注“A 转发”的 P 卡片；
- B 的曝光记录保留 `source_account_id=A`；
- B 转发后，B 的关注者可继续收到该传播链；
- 已曝光的 P 再次出现时分数为 0，但仍留下新的、带来源的曝光记录；
- 转发计数准确且重复转发受约束；
- 屏幕只包含当前账号实际展示的卡片，过期页面不能提供可执行 `post_id`；
- 手机组件通过 build、archive 和 checkpoint 使用同一 runtime-scoped catalog 往返；
- 一个独立 SQLite 事务或 KERN bundle 端到端回滚后不会留下部分曝光或转发；
- 使用同一实验 seed 重跑，feed、曝光与累计转发曲线一致。

当前聚焦测试覆盖推荐只读、真实页面曝光校验、转发/点赞/评论前置条件、扁平评论、
重复点赞与转发拒绝、下一 tick 转发可见、多跳传播、8/3 页面上限、页面去重、重复曝光
留痕、已曝光分数归零、SQLite 与 KERN Bundle 事务提交/回滚、checkpoint 边界、旧 schema
拒绝、旧 schema 与旧帖子契约拒绝、Package effect/recipe 注册、`ScreenComponent` 往返、
社交 workflow 感知边界、LLM 输出校验、海平面 world 生成和两条件 seed 对齐。pilot、300 Agent
smoke 和同 seed 完整实验复跑仍待覆盖。
