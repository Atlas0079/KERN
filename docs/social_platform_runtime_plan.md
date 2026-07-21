# 社交平台与谣言传播实验现状

> 状态：设计与研究参考。本文保留 RumorSpread 的架构动机、实验设计和后续建议；其旧的
> `Data/RumorSpread/` 与 `runtime_config.rumor_spread.*` 路径已迁出。当前可运行的社交世界包
> 是 `Packages/SU7Crisis`，使用 `runtime_config.su7_crisis.package.smoke.json`。

本文记录 KERN 社交平台相关工作的合并说明。它覆盖两层内容：

1. 社交平台外部 runtime 基建：账号、帖子、推荐、曝光、互动、手机屏幕和 effects。
2. 谣言传播实验场景：用 social runtime 模拟谣言曝光、打开、互动、澄清触达和未来干预。

稳定架构事实应同步到仓库根目录 `AGENTS.md`。本文用于解释社交平台子系统为什么这样设计、目前测试场景是什么、做到哪里、下一步还缺什么。

## 当前分层

```text
KERN runtime tick loop
-> WorldState agents and phones
-> ScreenComponent as short-term operable context
-> social platform effects
-> external_runtime_bridge
-> SQLiteSocialPlatformRuntime
-> social SQLite tables and checkpoint snapshots
```

社交平台 runtime 自己维护账号、帖子、推荐、曝光、浏览、互动和 checkpoint 状态。KERN 不直接把平台数据库暴露给 agent，而是通过手机 `ScreenComponent` 和领域 effects 给 agent 一个可操作入口。

谣言传播实验不是单独重写一套平台，而是在这个 runtime 上增加：

- 特定场景数据。
- 社交活动 gate。
- 谣言/澄清 seed。
- 未来干预和指标导出。

## 当前边界

第一版已经完成：

- agent 能刷推荐流、点开帖子、发帖、点赞、取消点赞、评论、转发、关注账号。
- 社交行为会产生 KERN event、`memory_hint`、SQLite 行为记录和 KERN 侧手机屏幕状态。
- planner 不直接依赖 raw `post_id`，grounder 在屏幕上下文新鲜时才获得可操作 ID。
- social runtime 可以由 config 声明，并随 KERN checkpoint 生命周期保存/恢复自己的 SQLite 快照。
- `RumorSpread` 场景已经用 `SocialActivityGateTick` 替代默认多动作 agent loop。

暂时不做：

- 设备/app session 安全边界。
- 负反馈、拉黑、静音、不感兴趣。
- 通知、私信。
- UI、Web server。
- 图片/视频。
- 复杂 embedding 推荐。
- 真实多用户并发服务。

安全边界目前很薄：agent 通过目标手机实体的 `ScreenComponent.runtime_id/account_id` 使用平台账号。后续如果出现越权、共享设备、伪造账号等问题，再升级到 `SocialAppComponent`、`DeviceAccessComponent` 或 session 模型。

## 已实现代码地图

社交平台 SQLite runtime：

```text
KERN/external_runtimes/social_platform.py
```

核心能力：

- `SQLiteSocialPlatformRuntime`
- `upsert_account(...)`
- `invoke(operation, payload, context)`
- `save_checkpoint(context)`
- `restore_checkpoint(context)`
- `observe_feed`
- `observe_post`
- `create_post`
- `interact_post`
- `follow_account`

当前维护的 SQLite 表：

```text
runtime_meta
accounts
account_interests
posts
post_tags
comments
likes
reposts
follows
feed_sessions
exposures
view_history
action_traces
checkpoint_snapshots
```

KERN 侧 bridge：

```text
KERN/external_runtime.py
```

领域 effects：

```text
KERN/executor/_effect_social_platform.py
KERN/executor/_effect_social_activity.py
```

组件：

```text
KERN/models/components/screen.py
KERN/models/components/social_behavior.py
```

Workflow profile：

```text
KERN/agent_workflow/view_profile.py
```

Seed/profile 工具：

```text
KERN/external_runtimes/social_seed.py
KERN/external_runtimes/social_profile_seed.py
tools/generate_social_profiles.py
tools/social_profile_report.py
tools/convert_pheme_to_social_seed.py
```

## ScreenComponent

`ScreenComponent` 是 planner/grounder 和外部平台之间的短期可操作上下文。它挂在手机、电脑或其他终端实体上。

典型手机实体：

```json
{
  "template_id": "Phone",
  "entity_name": "Student Phone",
  "components": {
    "TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
    "ScreenComponent": {
      "runtime_id": "social",
      "account_id": "acc_student_high_media",
      "app": "social_platform",
      "view": "blank",
      "title": "",
      "feed_items": [],
      "current_post": null,
      "selected_post_id": "",
      "cursor": 0,
      "updated_tick": 0
    }
  }
}
```

字段含义：

- `runtime_id` 指向 `external_runtime_bridge` 里的 adapter key。
- `account_id` 是外部社交平台 runtime 内的账号 ID。
- `view` 表示当前屏幕状态，例如 `feed`、`post`、`blank`。
- `feed_items` 保存当前屏幕上可见的帖子卡片，包含 `post_id`、作者、摘要、标签和推荐原因。
- `current_post` 保存当前打开帖子的可见内容和评论摘要。
- `selected_post_id` 保存最近选中的帖子，供后续评论、点赞、转发等 effect 默认使用。

这个组件不是平台数据库。它只保存“屏幕此刻显示了什么”。平台真实状态仍属于 `SQLiteSocialPlatformRuntime`。

## Planner / Grounder 隔离

社交平台使用三层上下文：

```text
social runtime state: 平台真实状态，KERN 不直接暴露给 planner/grounder
agent memory: 给 planner 的语义连续性，例如“刚才看到一条校园健康相关传言”
phone ScreenComponent: 给 grounder 的短期可操作引用，例如 post_id、slot、current_post
```

planner 不应该依赖或输出原始 `post_id`。planner 只表达意图，例如“打开推荐页第一条帖子”或“评论当前帖子”。grounder 负责把这个意图落到当前屏幕状态：

```text
planner: 我想看看推荐页第一条帖子
grounder: 从 phone.ScreenComponent.feed_items[0].post_id 取出 post_id
effect: ObserveSocialPost(target="phone", slot=0)
```

grounder 屏幕上下文有新鲜窗口，默认：

```text
grounder_screen_context_window_ticks = 2
```

如果 agent 最近 2 tick 内执行过社交浏览类动作，grounder 可见：

- `feed_items[*].post_id`
- `current_post.post_id`
- `selected_post_id`
- `runtime_id/account_id`
- `cursor`

如果屏幕上下文过期，grounder 不应继续复用旧 `post_id`，应先重新观察 feed 或帖子。

## Social Effects

已实现 effect：

```text
ObserveSocialFeed
ObserveSocialPost
CreateSocialPost
InteractSocialPost
FollowSocialAccount
SocialActivityGateTick
```

前五个是平台动作，`SocialActivityGateTick` 是谣言传播场景的行动机会 gate。

调用链：

```text
recipe / decision
-> WorldExecutor
-> _effect_social_platform.py
-> target phone ScreenComponent
-> external_runtime_bridge.invoke(runtime_id, operation, payload, context)
-> SQLiteSocialPlatformRuntime.invoke(...)
-> update ScreenComponent
-> SocialFeedObserved / SocialPostObserved / ...
```

### ObserveSocialFeed

用途：agent 查看推荐流。

输入：

```json
{
  "effect": "ObserveSocialFeed",
  "target": "phone",
  "limit": 5
}
```

返回 `SocialFeedObserved`。handler 会把 `items` 写入 `ScreenComponent.feed_items`，并设置：

```text
view = "feed"
cursor = event.cursor
current_post = None
selected_post_id = first item post_id if present else ""
updated_tick = current tick
```

### ObserveSocialPost

用途：agent 点开帖子。

输入：

```json
{
  "effect": "ObserveSocialPost",
  "target": "phone",
  "slot": 0
}
```

`post_id` 可以显式传入；如果没有传，handler 从目标手机屏幕解析：

```text
slot -> ScreenComponent.feed_items[slot].post_id
selected_post_id -> ScreenComponent.selected_post_id
current_post.post_id -> ScreenComponent.current_post.post_id
```

返回 `SocialPostObserved`。handler 会更新 `current_post`、`view = "post"` 和 `selected_post_id`。

### CreateSocialPost

用途：agent 发布新帖子。

输入：

```json
{
  "effect": "CreateSocialPost",
  "target": "phone",
  "text": "今天户外活动很好玩。",
  "tags": ["kindergarten", "outdoor"]
}
```

返回 `SocialPostCreated`，并把新 `post_id` 写入手机的 `selected_post_id`。

### InteractSocialPost

用途：agent 对帖子互动。

输入：

```json
{
  "effect": "InteractSocialPost",
  "target": "phone",
  "slot": 0,
  "action": "comment",
  "text": "我记住了。"
}
```

支持 action：

```text
like
unlike
comment
repost
```

如果未显式传 `post_id`，使用与 `ObserveSocialPost` 相同的屏幕解析规则。

### FollowSocialAccount

用途：agent 关注另一个账号。

输入：

```json
{
  "effect": "FollowSocialAccount",
  "target": "phone",
  "target_account_id": "acc_teacher"
}
```

返回 `SocialAccountFollowed`。

## 推荐算法

当前 runtime 实现轻量可解释推荐，不做 embedding。`observe_feed` 只选择 `created_tick <= current_tick` 的 active posts，避免未来计划发布的澄清或噪声帖提前出现。

当前公式：

```text
score =
  2.0 * interest_match
+ 1.5 * follow_boost
+ 1.2 * freshness
+ 1.0 * engagement
+ 0.8 * author_affinity
+ 0.4 * exploration_noise
- 2.0 * seen_penalty
```

字段来源：

- `interest_match` 来自 `account_interests` 与 `post_tags`。
- `follow_boost` 来自 `follows`。
- `freshness` 来自 `created_tick` 与当前 tick。
- `engagement` 来自 like/comment/repost 计数。
- `author_affinity` 来自该账号历史 action traces。
- `exploration_noise` 基于 run/account/post/tick/cursor 的稳定随机探索。
- `seen_penalty` 来自该账号历史 exposures。

## Event 和 Memory Hint

社交平台 runtime 返回 event dict 和 `memory_hint`。effect handler 不改写这些事件，只原样返回，并在同一 effect 内更新目标手机的 `ScreenComponent`。

推荐页曝光默认低权重：

```json
{
  "memory_hint": {
    "should_remember_by_default": false,
    "importance": 0.1
  }
}
```

点开帖子、评论、转发、发帖、关注默认更容易进入记忆。推荐页曝光即使进入短期记忆，也通常会因为低权重和衰减较快而很快消失。

## Checkpoint 和事务约束

social runtime 已实现：

```python
save_checkpoint(context)
restore_checkpoint(context)
```

第一版用 JSON 快照保存平台表状态，存入 `checkpoint_snapshots`。恢复时按 `run_id/tick` 重建 social runtime 表。KERN checkpoint save 或 social checkpoint save 失败时都应中断，不允许静默降级到不同步状态。

KERN 的 `WorldExecutor` 可以回滚 `WorldState`，但第一版 `SQLiteSocialPlatformRuntime` 的写入不会自动参与 KERN bundle 回滚。因此保守约束仍然有效：

- 社交平台写操作尽量独立成单 effect bundle。
- `CreateSocialPost`、`InteractSocialPost`、`FollowSocialAccount` 不要和其他可能失败的 world mutation 混在同一个 bundle。
- `ObserveSocialFeed`、`ObserveSocialPost` 虽然主要是观察，但会写 exposure/view history，也建议单独成 bundle。
- 如果必须组合多个动作，把社交平台 effect 放在 bundle 最后。

后续如果需要强一致性，再给 `external_runtime_bridge` 增加外部事务接口。

## SocialActivityGateTick

`SocialActivityGateTick` 是谣言传播场景的关键控制流。它解决的问题是：社交平台微动作不应该通过默认 `AgentControlTick(max_actions=50)` 在同一 tick 内反复执行。

实现位置：

```text
KERN/executor/_effect_social_activity.py
KERN/effect_contract.py
KERN/agent_workflow/runtime.py
```

新增 helper：

```python
run_social_activity_cycle(...)
run_social_activity_batch(...)
```

单 agent 路径复用 `run_workflow_cycle(...)` 的 memory patch、decision contract、command 编译和 operation 执行路径，并通过 `max_commands` 限制一次机会最多执行指定数量的命令。批量路径由 `run_social_activity_batch(...)` 承接，支持串行模式和 RumorSpread 专用的并行决策、串行提交模式。默认 `max_actions=1`。

当前 binder 支持：

```text
max_agents_per_tick
max_actions_per_agent
default_screen_context_window_ticks
base_rate_multiplier
provider_id
```

默认值：

```text
max_agents_per_tick = 999999
max_actions_per_agent = 1
default_screen_context_window_ticks = 2
base_rate_multiplier = 1.0
provider_id = ""
decision_mode = serial
max_decision_workers = 1
```

候选 agent 要求：

- 有 `SocialBehaviorComponent`。
- 有 `AgentControlComponent` 且 `enabled=true`。
- inventory 中存在带 `ScreenComponent` 的 phone。
- phone screen 有非空 `runtime_id/account_id`。
- 能找到 workflow provider。当前 RumorSpread 不在 reaction 或 agent 数据里指定 provider，默认使用 runtime config 构建出的 `default_action_provider`。`provider_id` 只作为未来多 provider 路由保留；如果命名 provider 无法在 `action_providers` 中解析，会回退到 default provider。

当前概率公式：

```text
probability =
  clamp01(base_activity_rate)
  * base_rate_multiplier
  * active_hour_multiplier
```

规则：

- agent 有 `social_action_cooldown` 状态时直接跳过。
- 如果 `active_hours` 为空，`active_hour_multiplier = 1.0`。
- 如果 `active_hours` 非空，当前小时命中则为 `1.0`，否则为 `0.35`。
- 当前小时读取 `ws.game_time.hour`；如果不存在，则用 `tick % 24`。
- 稳定随机数来自 `run_id | tick | agent_id | SocialActivityGateTick`。
- `fatigue` 当前只是 `SocialBehaviorComponent` 的预留字段，不参与 gate 概率，也不会自动变化。

当前只在两个机会类型之间选择：

- `routine_browse`
- `expression_opportunity`

这只影响 `mode_context` 提示，不直接决定具体动作。具体行为仍由 LLM/provider 决定。

### 并行决策模式

`SocialActivityGateTick` 支持一个 RumorSpread 专用的批量决策模式：

```json
{
  "decision_mode": "parallel_decide_serial_commit",
  "max_decision_workers": 16
}
```

这是场景级黑魔法，不是 KERN 通用 tick phase。它的语义是：

```text
串行筛选候选 agent
-> 串行准备每个 agent 的 workflow input 和 memory patch
-> 并行调用 workflow.decide(...)
-> 按稳定 agent 顺序串行验证、编译 command、执行 effect bundle
```

worker 线程只执行 LLM/provider 的 `decide(...)`，不写 `WorldState`，也不直接调用 `WorldExecutor`。因此它加速最慢的 LLM 等待，但仍保留 KERN 串行提交、事件顺序和 bundle 回滚语义。默认 `decision_mode=serial`；当前 committed RumorSpread 5-agent smoke 和 generated 100-agent smoke 都已经显式打开 `parallel_decide_serial_commit`。

### 时间消耗规则

`SocialActivityGateTick` 发放行动机会本身不等于消耗时间。当前规则由 recipe 明确写入世界状态：

- 不消耗 tick：`BrowseSocialFeed`。它只刷新手机屏幕上的推荐流，不添加 cooldown 状态。
- 消耗 1 tick：`OpenSocialPost`、`CommentSocialPost`、`LikeSocialPost`、`RepostSocialPost`、`CreateSocialPost`。这些 recipe 会在社交平台 effect 成功后追加 `AddStatus(self, social_action_cooldown, duration_ticks=2)`。

实现上，gate 不再读取 workflow 内部执行摘要，也不按 verb 判断耗时。它只检查 agent 是否有 `StatusComponent.social_action_cooldown`。正式 RumorSpread 通过 `AdvanceTick -> StatusTick` 让该状态自动过期：某 agent 在 tick N 做了耗时动作后，tick N+1 会被跳过，tick N+2 可再次获得机会。

## Workflow View Profile

社交传播场景不能直接沿用具身智能场景的完整物理感知。若多个 agent 位于同一地点，感知链路可能把同地点实体和事件塞进 prompt/记忆，造成上下文污染。

当前 runtime config 支持：

```json
{
  "env": {
    "WORKFLOW_VIEW_PROFILE": "social_platform"
  }
}
```

内置 profile：

- `embodied_default`：默认具身场景行为。
- `social_platform`：关闭物理实体、地图、可达地点、同地点记忆污染；保留 agent 身份、记忆、inventory phone 和 grounder 的 phone screen context。
- `social_platform_debug`：调试用，关闭地图/可达地点和同地点记忆，但保留 visible entities。

这不是单纯 prompt 层过滤。profile 会被注入 workflow view：

- `observer.build_agent_perception(...)` 根据 profile 裁剪 LLM 可见信息。
- `memory_policy.build_memory_patch(...)` 根据 profile 过滤同地点无关事件和他人 social feed 事件。
- 默认 profile 保持旧场景兼容。

## 已清理场景：SocialPhone

`Data/SocialPhone/` 和 `runtime_config.social_phone.smoke.json` 已清理。

它原本用于验证 phone screen、social effects、runtime seed、recommendation、SQLite 写入和 recipe grounder 条件。这个目的已经完成，现在相关覆盖迁移到：

- `tests/test_social_platform_effects.py`：直接验证 social effects、screen 更新、grounder 新鲜窗口、social memory。
- `tests/test_rumor_spread_config_runtime.py`：用正式 `RumorSpread` config 验证 config-declared SQLite runtime、seed、recipes 和 carried-phone 条件。
- `Data/RumorSpread/`：作为后续唯一正式社交传播测试场景。

## 当前测试场景：RumorSpread

用途：验证谣言传播实验的第一版控制流。它是正式 LLM 场景。

配置：

```text
runtime_config.rumor_spread.smoke.json
```

关键 env：

```text
USE_LLM=1
WORLD_JSON=RumorSpread/World.json
RECIPES_JSONS=RumorSpread/Recipes.json
REACTIONS_JSONS=RumorSpread/Reactions.json
ENTITIES_DIRS=RumorSpread/Entities
MAX_TICKS=5
WORKFLOW_CONTRACT_ON_ERROR=degrade_to_noop
WORKFLOW_VIEW_PROFILE=social_platform
EXTERNAL_RUNTIMES_JSON=social sqlite runtime with Data/RumorSpread/social_seed.json
```

场景数据：

```text
Data/RumorSpread/World.json
Data/RumorSpread/Entities/rumor_agents.json
Data/RumorSpread/Recipes.json
Data/RumorSpread/Reactions.json
Data/RumorSpread/social_seed.json
```

世界：

- 一个地点：`rumor_lab_room`。
- 五个 agent：
  - `agent_student_high_media`
  - `agent_worker_low_media`
  - `agent_extrovert_commenter`
  - `agent_cautious_parent`
  - `agent_quiet_observer`
- 五部手机，分别放在对应 agent inventory 中：
  - `phone_student_high_media`
  - `phone_worker_low_media`
  - `phone_extrovert_commenter`
  - `phone_cautious_parent`
  - `phone_quiet_observer`
- 一个环境 scope：`rumor_lab_env`，`light_level=2`。
- 没有 paths；物理移动不是这个测试重点。

agent 和行为频率：

`agent_student_high_media` / Student High Media：

- 平台账号：`acc_student_high_media`。
- 性格/背景：时间灵活、频繁查看社交媒体、会快速响应校园健康安全讨论的学生。
- `AgentControlComponent` 只表示该 agent 可被工作流驱动；provider 由 runtime config 的 default provider 决定。
- `SocialBehaviorComponent`：
  - `base_activity_rate=0.95`
  - `active_hours=[]`
  - `event_reaction_sensitivity=0.8`
  - `expression_opportunity_rate=0.6`
  - `routine_browse_rate=0.8`

`agent_worker_low_media` / Worker Low Media：

- 平台账号：`acc_worker_low_media`。
- 性格/背景：忙碌、浏览较少、对转发未经证实的信息更谨慎的工作者。
- `AgentControlComponent` 只表示该 agent 可被工作流驱动；provider 由 runtime config 的 default provider 决定。
- `SocialBehaviorComponent`：
  - `base_activity_rate=0.55`
  - `active_hours=[]`
  - `event_reaction_sensitivity=0.45`
  - `expression_opportunity_rate=0.25`
  - `routine_browse_rate=0.65`

`agent_extrovert_commenter` / Extrovert Commenter：

- 平台账号：`acc_extrovert_commenter`。
- 性格/背景：外向、喜欢参与讨论，但仍需根据可见证据决定动作。
- `SocialBehaviorComponent`：
  - `base_activity_rate=0.9`
  - `event_reaction_sensitivity=0.65`
  - `expression_opportunity_rate=0.85`
  - `routine_browse_rate=0.55`

`agent_cautious_parent` / Cautious Parent：

- 平台账号：`acc_cautious_parent`。
- 性格/背景：关心健康与安全，但不喜欢传播未经确认的信息。
- `SocialBehaviorComponent`：
  - `base_activity_rate=0.75`
  - `event_reaction_sensitivity=0.75`
  - `expression_opportunity_rate=0.45`
  - `routine_browse_rate=0.7`

`agent_quiet_observer` / Quiet Observer：

- 平台账号：`acc_quiet_observer`。
- 性格/背景：主要浏览观察，很少评论，除非上下文重要。
- `SocialBehaviorComponent`：
  - `base_activity_rate=0.45`
  - `event_reaction_sensitivity=0.35`
  - `expression_opportunity_rate=0.15`
  - `routine_browse_rate=0.85`

recipes 共 6 个：

- `BrowseSocialFeed`
- `OpenSocialPost`
- `CommentSocialPost`
- `LikeSocialPost`
- `RepostSocialPost`
- `CreateSocialPost`

RumorSpread 保留更接近传播实验的行为：浏览、打开、点赞、评论、转发、原创发帖。不把 unlike/follow 作为当前正式传播场景动作。

reactions 共 3 个：

- `WorldTickAdvanced -> SocialActivityGateTick`
  - `max_agents_per_tick=10`
  - `max_actions_per_agent=1`
  - `default_screen_context_window_ticks=2`
  - `decision_mode=parallel_decide_serial_commit`
  - `max_decision_workers=30`
- `WorldTickAdvanced -> EnvironmentConditionTick`
- `AdvanceTick -> StatusTick`

它不使用默认 `Data/Reactions.json` 的 `AdvanceTick -> AgentControlTick(max_actions_in_tick=50)`。

seed 账号：

- 五个 KERN agent 账号：
  - `acc_student_high_media`
  - `acc_worker_low_media`
  - `acc_extrovert_commenter`
  - `acc_cautious_parent`
  - `acc_quiet_observer`
- 谣言种子账号：`acc_seed`，显示名“本地生活观察”。
- 官方账号：`acc_official`，显示名“校务通知”。
- 背景账号：`acc_background`、`acc_food_updates`、`acc_local_transit`、`acc_club_events`、`acc_health_life`。

seed 帖子：

- tick 0：17 条背景帖，覆盖校园、本地、食堂、交通、活动、健康、通知等标签。
- tick 1：1 条背景帖。
- tick 1：1 条谣言种子帖：
  - `post_rumor_seed_001`
  - 内容是“学校附近的饮水机不安全，很多人已经在转了，大家最好先别喝”
  - tags：`rumor/health/campus/local`
- tick 3：1 条官方澄清帖：
  - `post_clarification_001`
  - 内容是“关于饮水机安全的相关说法正在核实，请以官方检测公告为准，不要传播未经确认的信息”
  - tags：`clarification/health/campus/local`

总帖子数当前为 20 条。

follow：

- 五个 agent 账号都关注 `acc_seed`、`acc_official` 和所有背景账号。

这个场景目前能验证：

- 社交传播场景使用自己的 gate，而不是默认 agent loop。
- 五个 agent 因为 `SocialBehaviorComponent` 参数不同，获得行动机会的概率、冷却和表达倾向不同。
- 5-agent smoke 也通过并行 LLM 决策、串行 world commit 运行；并行只覆盖 provider `decide(...)`，不会并行写 `WorldState`。
- 推荐流只展示 `created_tick <= current_tick` 的帖子，因此 tick 3 的澄清不会提前出现。
- LLM 每次被 gate 选中后最多执行一个社交 command。
- `WORKFLOW_VIEW_PROFILE=social_platform` 避免五个同房间 agent 互相污染物理感知和记忆。

还不能证明：

- 正式干预策略效果。
- 谣言/澄清的专门数据模型。
- 统计 dashboard。
- 100-agent 生成数据和 smoke config 已存在，但还没有跑出稳定可复现实验曲线或统计结论。
- 显著事件 bonus 对行动概率的影响。

## 临时测试工具：5-agent LLM Smoke

还有一个生成式临时 smoke 脚本：

```text
tools/run_rumor_spread_5agent_llm_smoke.py
```

它保留为调试工具，会在：

```text
checkpoints/rumor_spread_5agent_llm_smoke/generated_data/
```

生成一个临时 `RumorSpread5Agent` 场景，用于带 run name 的一次性 LLM smoke。正式 committed 场景已经是 5-agent 版本，因此这个脚本主要用于隔离输出目录、stream 日志和指标摘要。

agent：

- `Student High Media`
- `Worker Low Media`
- `Extrovert Commenter`
- `Cautious Parent`
- `Quiet Observer`

它使用同一套 seed 主题：

- tick 0 背景帖。
- tick 1 饮水机安全谣言。
- tick 3 官方澄清。

它的用途：

- 跑短程 DeepSeek-compatible LLM smoke。
- stream 每 tick 的 gate 选择、agent command、social result。
- 汇总 SQLite 表计数、`action_traces_by_tick`、`rumor_exposures_by_tick`、`clarification_exposures_by_tick`。
- 检查 `social_platform` view profile 下的 perception 是否裁剪了物理污染。

它更像研究/调试脚本，还不是正式 committed scenario 数据。

## PHEME 数据接入

当前决定优先使用 PHEME 作为真实社交平台文本来源，而不是让 LLM 凭先验生成“真实谣言”。

PHEME 在本项目中的职责是提供外部实验输入：

- source tweet 文本。
- rumor / non-rumor 标签。
- 事件目录名。
- source tweet 的发布时间，用于映射到 KERN tick。
- source tweet 作者信息可选保留；默认不把 PHEME 作者映射到 KERN agent。

转换脚本：

```powershell
python tools\convert_pheme_to_social_seed.py <PHEME解压目录> `
  --rumor-count 1 `
  --noise-count 100 `
  --output Data/RumorSpread/social_seed.pheme.generated.json
```

脚本识别：

```text
<event>/rumours/<thread>/source-tweets/*.json
<event>/non-rumours/<thread>/source-tweets/*.json
```

输出兼容 `seed_social_platform_runtime_from_file(...)`。

当前第一版只导入 PHEME source tweets。PHEME reactions 后续可以作为预置评论、预置转发或评估对照，但优先级低于让 KERN LLM agents 在运行中产生互动数据。

## 100-agent 生成场景状态

当前已经有 100-agent RumorSpread 数据生成器和生成后的 committed smoke 数据：

```text
tools/generate_rumor_spread_100.py
Data/RumorSpread/generated_100/
runtime_config.rumor_spread.100agent.smoke.json
```

生成器会基于 `social_profile_seed.generate_social_profiles(...)` 创建：

- 100 个 KERN agent 和对应 phone。
- 100 个社交平台账号、兴趣权重和 follow graph。
- 背景帖、多个谣言种子帖和多个澄清帖。
- generated 版本的 `World.json`、`Entities/generated_agents.json`、`social_seed.json`、`profiles.json` 和 `Reactions.json`。

generated 100-agent reactions 使用：

```text
max_agents_per_tick = 100
decision_mode = parallel_decide_serial_commit
max_decision_workers = 30
```

这说明“profile -> scenario 生成器”和基础大规模 smoke 数据已经落地。尚未完成的是：用该配置跑出可复现实验结果、沉淀指标导出、比较干预组和 baseline，并证明 100-agent 传播曲线有研究意义。

## 反应类发帖还缺什么

`CreateSocialPost` 本身不应该凭空发生。它只是一个可执行动作。让 LLM 有理由发帖，需要给它上下文来源。

建议后续新增以下事件或信息源：

- `RumorSeedEvent`：谣言种子出现。
- `ClarificationEvent`：官方或专家澄清出现。
- `OfflineSituationEvent`：线下事实或生活事件，例如学校通知、通勤异常、社区传闻。
- `SocialSalienceEvent`：某个话题在平台上显著升温。
- social memory：agent 最近看到、打开、评论、转发过的相关内容。

这些事件进入 event log 和 memory policy 后，`SocialActivityGateTick` 可以提高相关 agent 的行动机会，并在 `mode_context.salient_context` 中解释触发原因。

## 干预和指标状态

第一版建议实验组：

- `baseline`：无干预。
- `clarification`：官方账号或专家账号发布澄清帖。
- `downrank_or_label`：平台对谣言帖打标或降权。

当前尚未实现正式 `rumors` / `interventions` 表，也没有正式干预 effect。建议未来把干预做成 social runtime 的正式 operation，并通过 KERN effect 暴露，例如：

```text
ApplySocialIntervention
```

可视化面板应独立于 KERN runtime 实现。它读取：

- KERN archive/checkpoint：tick、agent、event log、interaction log。
- social SQLite：posts、post_tags、comments、likes、reposts、follows、exposures、view_history、action_traces、未来的 rumors/interventions 表。

第一版指标：

- 每 tick 谣言曝光数。
- 每 tick 谣言打开数。
- 每 tick 评论/转发/点赞数。
- 澄清帖曝光数和打开数。
- 谣言传播峰值。
- 干预前后曲线对比。
- 关键账号或关键帖子排行。

当前 social SQLite 已经有曝光、打开和互动原始表；但还没有正式指标导出模块或 dashboard。`tools/run_rumor_spread_5agent_llm_smoke.py` 中的临时统计逻辑可作为指标导出设计参考。

## 当前测试覆盖

已存在相关测试：

```text
tests/test_social_platform_runtime.py
tests/test_social_platform_effects.py
tests/test_rumor_spread_config_runtime.py
tests/test_social_activity_gate.py
tests/test_social_profile_seed.py
tests/test_workflow_view_profile.py
tests/test_social_prompt_redaction.py
tests/test_convert_pheme_to_social_seed.py
```

常用验证：

```powershell
python -m unittest tests.test_social_activity_gate tests.test_social_platform_runtime tests.test_social_platform_effects tests.test_rumor_spread_config_runtime
python tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
```

## 下一阶段建议

下一阶段不要重复建设已完成的 gate/profile/最小场景，而是按实验能力补齐：

1. 设计并实现 social runtime 的 `rumors` / `interventions` 数据模型。
2. 增加 `ApplySocialIntervention` 或同等正式 effect/runtime operation。
3. 把澄清帖、平台标签、降权/限流等干预接入推荐算法和统计表。
4. 为 `SocialActivityGateTick` 接入显著事件 bonus 和 `salient_context`。
5. 增加指标导出工具，先输出 CSV/JSON，再做 dashboard。
6. 用现有 100-agent 生成场景跑短程/中程 LLM smoke，沉淀可复现实验曲线。
7. 验证 agent 能基于新鲜屏幕上下文刷帖、打开、评论或转发，而不是依赖记忆里的裸 `post_id`。
