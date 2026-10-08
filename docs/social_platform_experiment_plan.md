# 社交平台实验实现状态

本文记录海平面两条件实验当前已经实现的工程状态和剩余验收工作。平台推荐、曝光、点赞、
扁平评论和转发的运行契约以 `social_platform_runtime_design.md` 为准。

## 背景帖传播控制（2026-09-22）

本实验检验后果聚焦与解决方案聚焦文案对转发行为的影响，不预设假设必然成立。
两组使用相同的背景帖传播控制：背景帖继续提供浏览情境，但不通过互动反馈扩大分发。

| 机制 | 背景帖 | 实验帖 |
| --- | --- | --- |
| 普通推荐中的兴趣、关注作者、新鲜度与探索 | 保留 | 保留 |
| 点赞、评论、转发操作及真实数据库记录 | 保留 | 保留 |
| 向关注者分发转发卡片 | 禁止 | 保留 |
| 累计转发对普通推荐分数的加权 | 关闭 | 保留 |
| 点赞、评论、转发形成的热门推荐加权 | 关闭 | 保留 |
| 页面上真实互动计数与本人已互动状态 | 保留 | 保留 |

两组运行配置的 `external_runtimes[].options.propagating_post_ids` 均设置为
`["sea_level_experiment_post"]`。列表明确指定允许转发分发和互动加权的帖子，其余帖子
按背景帖处理；不根据文案、hashtag 或 condition_id 猜测。列表不得为空、重复或引用
seed 中不存在的帖子。正式配置与本地 12 tick 配置采用相同规则。

实现复用现有 `recommender.select_page`，由 SocialPropagation Package 的 SQLite adapter
装配 `ExperimentalFeedRecommender`。无需改变 Agent 决策、动作接口或事务边界。
未配置该选项的其他社交场景继续使用普通推荐策略。该选项进入现有 Package runtime
identity；新实验从新建的空数据库开始，旧运行档案保留，不混入新结果或续跑旧 checkpoint。

这是一项受控传播设定，不代表真实平台的完整机制，也不保证提高实验帖转发率。
背景文案、公开互动计数、评论和 Agent 记忆仍可能影响选择；实验帖自身的扩散也会改变
后续页面。因此两组背景页面不保证完全相同，仍须分别报告曝光人数、曝光后的转发比例
与最终传播规模。背景帖转发是已记录的行为，不产生二次转发分发，不能据此推算背景传播级联。

文件分工：本文描述实验规则；`Packages/SeaLevelSocialExperiment/Study/study_config.v1.json`
保存帖子材料、人口、网络及访问计划参数；运行配置保存上述分发策略选项；
`social_platform_runtime_design.md` 说明推荐与持久化的技术契约。

## 社交专用 workflow

### 读后互动与导航分离（2026-09-30）

详情页决策任务改为“读完当前帖子后愿意进行哪些公开互动”，允许点赞、评论、转发或空互动。
原有动作说明、画像、帖子和页面状态继续进入同一个决策请求；推荐流仍判断是否点开卡片。
详情页请求不要求模型选择返回推荐流，session 在互动队列末尾通过既有 `BackToSocialFeed`
动作返回；空互动同样返回。导航仍经过原有动作、effect 和反馈链路，每 turn 最多阅读三条详情。
页面已有点赞或转发状态时，提示词要求不重复该动作。

先从现有 300 个画像中以固定 seed `20260930` 抽取 100 个，用同一批画像分别测试两篇帖子，
每画像每条件请求一次。该阶段使用统一的假设详情页：完整帖子、零互动计数、无评论、无历史记忆；
它不运行推荐、访问计划或传播。后续实际平台实验保留 300 人、12 tick 和背景传播控制，使用
新建数据库。两阶段均使用 Gemma，temperature 为 0.9，决策 max_tokens 为 1200。
模拟进程在本机运行，数据库、checkpoint、请求与回复记录保留在本机；学校服务器只提供
Gemma API。本机通过 SSH 转发调用 API，并使用独立的新运行目录。

实际运行复用 `step_and_record`，在每个 tick 完整执行并保存 checkpoint 后，记录两条件的
当 tick 与累计曝光人数、详情阅读人数、实验帖转发数、背景互动和请求错误；运行中的 tick
与已完成 tick 分开显示。原始请求、回复、数据库和旧实验档案保留，各辅助脚本与统计仅保留本地。

### 运行边界

社交 workflow 实现现有 `AgentWorkflow` / `AgentTurnSession` 协议。KERN 继续负责 turn、
`TurnFrame`、`SubmitAction` / `EndTurn`、动作解析、EffectBundle、拒绝反馈、replan 上限、
运行终止、checkpoint 和 failure report。

`SocialPlatformWorkflow` 是应用层鸭子类型实现；KERN 不增加社交调度 policy 或 `SkipTurn`。
`WorkflowRegistry` 仍然只注册和解析 workflow，
开发者只通过 `AgentControlComponent.provider_id` 选择它。访问判断、浏览状态机、社交专用
LLM 输入、领域输出校验和动作队列全部封装在该 workflow 及其 turn session 内。

`TurnRunner` 在每次 `next_step(ws, frame)` 时提供已结算的当前 `WorldState` 和只含调度、反馈、
计数的 `TurnFrame`。社交 session 直接读取 Agent 身份组件和手机 `ScreenComponent`，自行构造
严格的社交领域 perception。未被访问计划选中的 session 返回
`EndTurn(reason="not_scheduled")`，不读取页面、不调用 LLM，也不提交平台 effect。

### 配置与选择

社交 workflow 由 `applications/social_experiment` 应用层拥有和装配。应用通过现有
`WorkflowRegistry` 注入 KERN；Package 只定义世界与额外能力，不声明 workflow。
通用内置 kind 保留 `simple` 和 `llm`。运行社交实验使用
`python -m applications.social_experiment --config runtime_config.sea_level.solution.json`。

社交应用读取海平面实验 config 的顶层 `workflow_providers` 并注册：

```json
{"workflow_id": "social_platform", "kind": "social_platform"}
```

Agent 统一使用 `provider_id="social_platform"`。`social_platform` builder 从已加载 world Package
读取 `Data/Study/activation_schedule.json`、`Data/Study/actor_bindings.json` 和
`Study/study_config.v1.json` 中的稳定实验帖 ID；这些场景事实不写入 runtime config。

### 专用感知

社交 workflow 自己构造只与当前平台会话有关的 LLM 输入：

```json
{
  "schema_version": "social_decision_perception.v1",
  "tick": 12,
  "actor_id": "agent_001",
  "profile": {
    "profile_id": "social_profile_001",
    "natural_language_background": "……",
    "platform_friend_categories": ["大学同学", "工作同事", "家人亲属"],
    "big_five": {
      "openness": 0.0,
      "conscientiousness": 0.0,
      "extraversion": 0.0,
      "agreeableness": 0.0,
      "neuroticism": 0.0
    }
  },
  "screen": {
    "terminal_id": "phone_001",
    "runtime_id": "social_platform",
    "account_id": "account_001",
    "view": "feed",
    "updated_tick": 12,
    "feed_session_id": 101,
    "feed_items": []
  },
  "recent_social_memory": []
}
```

`feed_items` 仅包含屏幕已经公开的字段：帖子正文和可见 hashtag、原作者、直接转发者、来源类型、
发布时间/轮次、转发轮次、页面位置、点赞/评论/转发计数，以及当前查看者是否已经点赞或
转发。排序分数、全网关注图、未展示候选、其他 Agent 画像和全局指标不能进入感知。

感知中不包含地点、地图、路径、附近实体、普通背包、生命值、任务、对话参与者或世界事件。
人物背景、大五人格和 `platform_friend_categories` 来自 Agent 的实验身份组件。好友类别是
根据完整画像生成的角色设定，使用一至五个不重复的非空字符串；它描述平台主要联系对象，
不新增实际关注边，不规定点赞、评论或转发偏好。workflow 每次决策都将好友类别写入身份
提示词，不能只写入数据后遗漏于 LLM 上下文。正式生成输入由 study config 的
`population.friend_categories_path` 指定，必须覆盖全部画像 ID。手机仍由
`social_propagation:ScreenComponent` 表达短期可操作页面；同一个刷新 effect 事务性写入的
页面字段是 workflow 构造本次 LLM 输入的事实来源。SQLite `feed_session` 保留为审计事实，
不作为第二套决策输入。workflow 只读取 `WorldState`，不直接写 SQLite 或 `WorldState`。

### 一次 turn 的流程

1. 屏幕不是当前 tick 的新鲜 feed 时，session 直接提交 `BrowseSocialFeed`，不调用 LLM。
2. KERN 提交浏览与曝光 bundle；下一次 `next_step(ws, frame)` 收到 committed feedback 后，
   workflow 从已更新的 `ScreenComponent` 构造社交 LLM 输入。
3. 页面为空或页面中没有实验帖时返回 `EndTurn`。
4. 实验帖实际出现在页面时进行一次 LLM 页面决策。输入包含完整当前页，不包含未展示帖子。
5. workflow 将模型选择转换为已有 Like、Comment、Repost action intents，依次返回
   `SubmitAction`；没有行为时直接返回 `EndTurn`。
6. KERN 每提交或拒绝一个 action 后重新提供 feedback。意外拒绝时，社交 session 结束当前
   turn，并在 trace 中保留拒绝结果；下一轮读取新鲜页面后重新决策。

第一版每次活跃会话只刷新一页，也只调用一次 LLM。一个 Agent 在同一 tick 不进行第二次
翻页或第二次页面决策。

### LLM 请求与领域输出

社交 workflow 直接进行一次结构化页面决策，不复用默认 workflow 的 Planner + Grounder
两次调用。当前页面已经提供可执行的 `post_id`，workflow 可以直接完成 grounding。

输出契约为：

```json
{
  "actions": [
    {"post_id": "post_001", "action": "like"},
    {"post_id": "post_001", "action": "comment", "text": "……"},
    {"post_id": "post_002", "action": "repost", "text": "……"}
  ],
  "decision_summary": "一至三句可审查的决定摘要"
}
```

- `actions=[]` 表示本页不进行互动。
- `action` 只允许 `like`、`comment`、`repost`。
- 每个 `(post_id, action)` 在一次响应中最多出现一次。
- `post_id` 必须来自当前 `feed_items`。
- comment 的 `text` 必须非空；repost 的 `text` 可为空。
- `decision_summary` 是简短决定摘要，不要求模型提供隐藏推理过程。
- workflow 根据当前查看者状态过滤已经点赞或转发的重复操作。

### 错误处理职责

| 层级 | 职责 |
|---|---|
| LLM client | 对 timeout、连接失败、429 和 5xx 做有界指数退避；耗尽后抛出请求错误 |
| 社交 workflow | 构造领域提示词，解析并严格校验上述 JSON，将解析或契约错误包装为现有 `KernFailure`，写完整 LLM trace 和 failure evidence |
| KERN action resolver | 校验 verb、目标手机、可见 `post_id` 和 recipe 条件，返回 ready 或 rejected |
| TurnRunner | 提交 EffectBundle、传回 `ActionFeedback`、限制 action/replan 数量并记录 action result |
| KernRuntime | 将未恢复的 workflow/LLM/执行错误标记为终止失败，保存唯一 developer-facing failure report |

模型输出格式错误不自动修复、不静默忽略，也不转换成 `no_action`。网络请求重试由现有 client
完成；同一语义决策不在 workflow 内额外重采样。

## 活跃调度在 workflow 内的封装

访问计划由实验工具在运行前生成，并作为不可变依赖传给 `SocialPlatformWorkflow`。workflow
在 `begin_turn(ws, TurnStart)` 中用 `actor_id` 和 `tick` 查询计划：

- 本轮未访问平台：返回 inactive session；该 session 第一次收到 frame 后立即返回
  `EndTurn(reason="not_scheduled")`；
- 本轮访问平台：返回正常 `SocialPlatformTurnSession`。

`TurnStart` 已经提供完成查询所需的 actor、tick 和 turn 信息。schedule 不需要进入
WorldState、SQLite 或 `ws.services`，也不接触推荐内容。schedule 的 schema、seed 和指纹写入
运行身份；恢复后，同一不可变 schedule 和当前 tick 能确定后续访问。所有实验 Agent 的现有
`AgentWakePolicyComponent` 使用 `NoActiveTask`，仅让 KERN 每轮调用一次社交 workflow；是否
打开平台仍由 schedule 决定。

未访问与打开后不互动通过三类证据区分：不可变 activation schedule 证明某 Agent 在某 tick
是否应访问；`feed_sessions` 证明页面是否实际打开；LLM trace 中的 `actions=[]` 证明打开后
选择不互动。inactive `EndTurn` 不写成 `no_action`，也不产生 LLM trace。

## 帖子主题与可见标签

`social_platform.v4` seed 已将帖子契约拆成：

- `ranking_topics`：受控词表中的内部推荐主题，只用于候选和排序，不进入 Agent 感知；
- `display_hashtags`：帖子作者写出的可见 hashtag，作为页面内容交给 Agent；
- `condition_id`：实验处理元数据，只用于运行归档和配对分析，不参与推荐。

海平面两篇实验帖的 `ranking_topics` 完全相同，固定为 `climate_risk` 与 `sea_level`。
后果/解决方案差异保留在正文、可见 hashtag 和 `condition_id` 中。这样算法给两个条件相同的
主题相关性机会，传播差异不会由内部标签预先制造。

40 条背景帖从受控内容模板目录取得明确的 `ranking_topics` 和 `display_hashtags`。场景生成器
只做确定性展开和严格验证：主题必须属于版本化词表、数组非空且无重复。第一版不使用 LLM
根据正文自动打标签，避免同一内容因模型或批次变化得到不同推荐权重。

若未来允许 Agent 原创发帖，再单独设计可版本化的主题分类器；该能力不属于当前实验。

## 结构化兴趣到推荐兴趣的映射

推荐兴趣是结构化画像中明确兴趣事实的可审计投影。它只影响内容主题相关性，不影响上线频率、
点赞、评论、转发或立场。自然语言背景不参与映射，大五人格也不参与推荐兴趣。

映射版本固定为 `social_interest_mapping.v1`：

| 画像来源 | 推荐权重 | 示例目标标签 |
|---|---:|---|
| `interests.science_topics` | 1.00 | climate_risk、environment、public_health、technology_society |
| `interests.practical` | 0.70 | reading、community、parenting、fitness、cooking、gardening、gaming、photography |
| `interests.aspirational` | 0.45 | travel、premium_tech、home_design、career_learning、financial_learning、culture_art |
| 所有账号的通用基线 | 0.10 | general_knowledge |

具体主题展开：

- `climate_risk` -> `climate_risk`, `sea_level`, `extreme_weather`
- `environment` -> `environment`, `ecology`, `climate_risk`
- `public_health` -> `public_health`, `health_risk`
- `technology_society` -> `technology`, `technology_society`
- 其他 practical/aspirational ID 映射到同名或稳定的规范化内容标签

同一标签由多个事实命中时取最大权重，不累加。账号 seed 为每个映射结果保存来源画像字段或
fact ID、映射版本和最终权重。两篇海平面实验帖使用相同的 `climate_risk` 与 `sea_level`
推荐标签；`consequence_focus` / `solution_focus` 只保存在实验元数据中。

这套映射表达“画像明确提到关注某主题，因此平台更可能推荐同主题内容”。它没有增加
“爱刷帖”“爱点赞”“容易转发”之类的平台行为标签。

## 过程状态与 SQLite

SQLite 保存所有已提交的平台事实。`social_platform.v4` 已实现：

- `feed_sessions`：每次打开/刷新页面一行，即使页面为空也保留；
- `exposures.feed_session_id`：将每张曝光卡片归到具体页面会话；
- feed card 的 `viewer_has_liked` / `viewer_has_reposted`：提供真实 UI 所需的查看者状态；
- `like_records`、`repost_records`、`comment_records`、`exposure_records` 和 feed session 只读 API；
- 点赞、评论和转发的 `source_exposure_id`，将互动关联到触发它的当前页面卡片。

推荐候选计算保持只读。页面打开本身与全部曝光在 RefreshFeed bundle 中事务性写入。
失败操作随外部事务回滚，不进入 SQLite 的已提交事实；其请求、拒绝和错误保存在 KERN
interaction/failure 记录及完整 LLM trace。`no_action` 属于 Agent 决策，不是平台操作，由
LLM trace 保存。这样可以从 SQLite 重建页面与成功互动，从 trace 重建决定和失败路径。

第一阶段优先保留这些原始过程状态，不在运行时固化统计解释或最终指标口径。

## 场景生成器处理原则

场景生成器必须根据 study config 和 seed 确定性生成账号、兴趣投影、关注网络、背景帖子、
activation schedule、Agent、手机和 generation manifest。正式实验需要多个 seed，因此保留
确定性生成器和测试；各次生成的 world、SQLite seed 和中间数据可以删除并重新生成。

允许删除只负责某次文件拼装的临时 wrapper。网络和访问计划的核心生成算法属于实验方法，
在实验完成、复核和论文归档前不能删除。

## 当前实现清单

### Workflow

- [x] 实现遵循现有鸭子类型协议的 `SocialPlatformWorkflow`；`TurnRunner` 只传递 `ws` 和
  `TurnFrame`，不构造领域 perception。
- [x] 实现 inactive/active 两种 turn session，并验证未调度 session 不调用 LLM、不提交平台 effect。
- [x] 实现 workflow 内部的社交 LLM 输入构造器，直接读取身份和屏幕组件，验证不会泄露
  地点、实体、排序分数和全局状态。
- [x] 在实验 world 中定义身份组件，保存 `profile_id`、第一人称背景、大五人格和平台主要好友类别。
- [x] 实现仅在实验帖曝光时发生的单次 LLM 页面决策与严格输出解析。
- [x] 实现浏览提交反馈、页面决策、多动作提交、no-action 和拒绝终止测试。
- [x] 为完整请求、响应、解析结果和 action results 接入现有 `LLMTraceRecorder` 与 failure evidence。

### 平台、场景与导出

- [x] 定义 activation schedule schema，并将不可变 schedule 注入 `SocialPlatformWorkflow`。
- [x] 实现并测试 `social_interest_mapping.v1`。
- [x] 将 SQLite 升级到 `social_platform.v4`，增加 feed session、viewer state、互动曝光归因和查询 API。
- [x] 定义严格的 study config schema。
- [x] 实现确定性场景/网络/activation schedule 生成器及 generation manifest。
- [x] 创建海平面实验 world Package、SQLite 配置和两个条件的运行配置。
- [x] 新建原始过程导出器，导出平台表、曝光过程、转发过程、per-tick summary 和 manifest。

### 剩余验收与分析

- [ ] 增加 10 Agent pilot、300 Agent smoke、同 seed 复跑和两条件 schedule 相等测试。
- [ ] 定义最终指标口径、统计报告和图表生成脚本。
- [ ] 在 pilot 后根据曝光覆盖、LLM 调用预算和失败率校准 study config。

### 已接受的延期

- 顶层 runtime config 显式声明 `social_propagation:sqlite_platform` 足以支持当前实验。
  Package 自主声明 runtime 不进入当前里程碑。
