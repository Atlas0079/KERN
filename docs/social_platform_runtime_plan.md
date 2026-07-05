# 社交平台外部 Runtime 计划

本文记录当前关于“仿微博社交平台 runtime 接入 KERN”的设计方向。它是给
LLM agent 使用的外部信息环境，不需要 UI，也不面向真人用户操作。

核心目标：KERN 只需要知道 agent 做了什么社交平台动作、平台返回了什么可见
信息、产生了什么事件和 memory hint。社交平台 runtime 自己维护账号、帖子、
推荐、曝光、浏览、互动和 checkpoint 状态。

## OASIS 参考取舍

OASIS 的社交仿真架构可以作为参考：它把系统拆成 platform、agents、actions、
recommendation system 和 simulation engine，并由平台维护帖子、评论、关系、
行为 trace 和推荐缓存。

本项目只借鉴结构，不照搬复杂度：

- 借鉴：平台状态由平台 runtime 自己拥有；agent 通过动作空间与平台交互；推荐
  同时考虑兴趣、关注网络、热度和新鲜度。
- 不借鉴：不做 UI，不做大规模分布式服务，不做复杂 embedding/TwHIN 推荐，
  不把平台内部数据库暴露给 KERN。

参考：

- https://docs.oasis.camel-ai.org/overview
- https://arxiv.org/html/2411.11581v4
- https://github.com/camel-ai/oasis

## 边界

KERN 继续作为模拟内核，负责：

- world state
- agent workflow
- recipe/effect/reaction
- event log / interaction log
- checkpoint 协调通知

社交平台 runtime 是外部领域系统，负责：

- 账号身份和兴趣画像
- 帖子、评论、点赞、转发、关注关系
- 推荐算法、feed session、曝光记录
- 浏览历史和行为 trace
- 自己的 SQLite 存储和 checkpoint save/restore

KERN core 只提供通用桥梁服务 `external_runtime_bridge`。社交平台应提供自己的
领域组件和专用 effect，不使用万能外部调用 effect。属于领域本身的 effect
必须放在单独文件中，方便后续按领域启用，例如：

```text
KERN/executor/_effect_social_platform.py
```

组件不要求单独文件边界。第一版可以只需要一个账号绑定组件，用来说明某个
KERN agent 对应哪个平台账号和 runtime。

## KERN-facing Capability Contract

KERN 不需要社交平台提供 UI、页面、HTML、数据库路径或原始 SQL 查询能力。
KERN 需要的是稳定的动作能力和 LLM 可消费的信息返回。

第一版 runtime 需要提供这些操作：

```text
observe_feed
observe_post
create_post
interact_post
follow_account
```

这些操作通过领域 effect handler 调用：

```text
KERN recipe/decision
-> ObserveSocialFeed / ObserveSocialPost / ...
-> _effect_social_platform.py
-> external_runtime_bridge.invoke(runtime_id, operation, payload, context)
-> SQLiteSocialPlatformRuntime.invoke(...)
-> KERN event dictionaries
```

返回事件必须是 KERN event dict，并且包含足够给 LLM agent 使用的摘要信息。
返回内容应该是“agent 此刻看到了什么”，而不是数据库原始行。

### observe_feed

用途：agent 查看推荐流。

返回轻量帖子卡片，适合放入当轮观察上下文：

```json
{
  "type": "SocialFeedObserved",
  "account_id": "acc_doudou",
  "items": [
    {
      "post_id": "post_001",
      "author_id": "acc_teacher",
      "author_display_name": "老师",
      "summary": "明天户外活动需要带水壶。",
      "tags": ["kindergarten", "outdoor"],
      "social_context": "12 likes, 3 comments",
      "why_visible": "interest_match"
    }
  ],
  "memory_hint": {
    "should_remember_by_default": false,
    "importance": 0.1
  }
}
```

推荐页曝光必须写入社交平台 runtime 的 exposure log，但默认不写入 agent
memory。agent 是否记住某条推荐页曝光，由后续 memory attention 决定。

### observe_post

用途：agent 点开某个帖子。

返回完整正文和评论摘要：

```json
{
  "type": "SocialPostObserved",
  "account_id": "acc_doudou",
  "post": {
    "post_id": "post_001",
    "author_id": "acc_teacher",
    "author_display_name": "老师",
    "text": "明天户外活动需要带水壶。",
    "tags": ["kindergarten", "outdoor"],
    "metrics": {
      "likes": 12,
      "comments": 3,
      "reposts": 1
    },
    "top_comments": []
  },
  "memory_hint": {
    "should_remember_by_default": true,
    "importance": 0.45
  }
}
```

### interact_post

用途：agent 对帖子互动。

第一版支持：

```text
like
unlike
repost
comment
```

返回事件：

```text
SocialPostInteracted
```

评论、转发、重要人物回复等事件可以给较高 `memory_hint`。普通点赞可以给低
权重 hint。

### create_post

用途：agent 发布新帖子。

返回事件：

```text
SocialPostCreated
```

### follow_account

用途：agent 关注另一个账号。

返回事件：

```text
SocialAccountFollowed
```

## KERN 领域 effect

第一版 KERN effect 建议保持小而明确：

```text
ObserveSocialFeed
ObserveSocialPost
CreateSocialPost
InteractSocialPost
FollowSocialAccount
```

effect handler 不直接操作 SQLite，也不理解推荐算法。它只负责：

1. 读取 effect 输入和 runtime context。
2. 解析 `runtime_id`、`account_id`、`post_id`、互动参数等。
3. 调用 `external_runtime_bridge.invoke(...)`。
4. 返回平台 runtime 产生的 KERN events。

如果找不到 runtime adapter，返回 executor error，并由 KERN 的事务/错误路径处理。

## 账号绑定组件

KERN world 中的 agent 需要能映射到平台账号。第一版可以新增一个轻量组件：

```json
{
  "SocialAccountComponent": {
    "runtime_id": "weibo",
    "account_id": "acc_doudou"
  }
}
```

effect 输入可以显式传 `account_id`，也可以默认从 actor 的
`SocialAccountComponent` 解析。优先级建议：

1. effect payload 中的 `account_id`
2. actor 的 `SocialAccountComponent.account_id`

## SQLite-first Runtime

社交平台 runtime 第一版直接使用 SQLite，不做纯内存实现。SQLite 文件由 runtime
自己管理；KERN 不读取、不写入、不传入保存路径。

建议包位置：

```text
KERN/external_runtimes/social_platform.py
```

建议主类：

```text
SQLiteSocialPlatformRuntime
```

它需要实现：

```python
invoke(operation, payload, context) -> list[dict]
save_checkpoint(context) -> list[dict] | None
restore_checkpoint(context) -> list[dict] | None
```

## SQLite 表设计

第一版建议表：

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

### runtime_meta

- `key`
- `value`

用于保存 schema version 等运行时元信息。

### accounts

- `account_id`
- `display_name`
- `bio`
- `created_tick`
- `follower_count`
- `following_count`
- `status`

### account_interests

- `account_id`
- `tag`
- `weight`

### posts

- `post_id`
- `author_id`
- `text`
- `created_tick`
- `like_count`
- `comment_count`
- `repost_count`
- `status`

### post_tags

- `post_id`
- `tag`

### comments

- `comment_id`
- `post_id`
- `author_id`
- `text`
- `created_tick`
- `like_count`
- `status`

### likes

- `account_id`
- `post_id`
- `created_tick`

### reposts

- `repost_id`
- `account_id`
- `post_id`
- `text`
- `created_tick`

### follows

- `follower_id`
- `followee_id`
- `created_tick`

### feed_sessions

- `account_id`
- `cursor`
- `last_refresh_tick`

### exposures

- `exposure_id`
- `account_id`
- `post_id`
- `tick`
- `source`
- `score`
- `position`
- `seen_count`

### view_history

- `account_id`
- `post_id`
- `tick`
- `view_type`

### action_traces

- `trace_id`
- `account_id`
- `operation`
- `target_type`
- `target_id`
- `tick`
- `payload_json`

### checkpoint_snapshots

- `run_id`
- `tick`
- `time_str`
- `snapshot_json`
- `created_at`

第一版可以用 JSON 快照保存全部平台状态，恢复时用该快照重建表。后续如果数据量
变大，再改成增量 checkpoint 或 SQLite backup。

## 推荐算法

第一版做轻量微博式推荐，不做 embedding。候选来源：

```text
followed_authors: 40%
interest_match: 40%
hot_explore: 20%
```

推荐分数：

```text
score =
  2.0 * interest_match
+ 1.5 * follow_boost
+ 1.2 * freshness
+ 1.0 * engagement
+ 0.8 * author_affinity
+ 0.4 * exploration_bonus
- 2.0 * seen_penalty
- 3.0 * negative_feedback
```

字段含义：

- `interest_match`：账号兴趣 tags 与帖子 tags 的重合和权重。
- `follow_boost`：是否关注作者。
- `freshness`：根据当前 tick 和帖子创建 tick 衰减。
- `engagement`：基于点赞、评论、转发的热度。
- `author_affinity`：agent 过去是否看过、互动过该作者内容。
- `exploration_bonus`：小随机项，避免推荐完全固定。
- `seen_penalty`：已经曝光过的帖子降权。
- `negative_feedback`：后续支持不感兴趣、拉黑、静音后使用。

推荐结果应该可复现。第一版可以用 `run_id/account_id/tick/cursor` 派生随机种子，
避免恢复后同一 tick 的推荐流漂移。

## 记忆机制方向

社交平台会制造大量低价值观察。如果每条推荐页曝光都进入固定 tick 的短期记忆，
agent 上下文会很快被污染。因此更通用的方向是升级 KERN 的短期记忆机制：
从 FIFO/固定窗口改为“权重驱动的短期记忆队列”。

事件本身仍然是客观事实，记录在 `WorldState.event_log`。事件生产者可以提供
`memory_hint`，但最终权重应该由 agent workflow 决定，因为同一个事件对不同
agent 的意义不同。

建议新增模块：

```text
KERN/agent_workflow/memory_attention.py
```

职责：

- 将事件和 interaction delta 转成 actor-specific memory candidates。
- 根据 salience、self relevance、goal relevance、social relevance、interest
  match、novelty、emotional weight 等因素打分。
- 对现有短期记忆应用衰减。
- 优先遗忘低权重记忆。
- 将高权重或 agent 显式保留的记忆放入 mid-term preparation。

短期记忆条目可以包含 `current_weight`、`decay_rate`、`created_tick`、
`last_accessed_tick`、`source` 和 `tags`。普通推荐页曝光可以快速遗忘；点开
帖子、评论、分享、重要人物回复、目标相关内容会保留更久。中期记忆整理可以
后续异步完成。

## Checkpoint 同步

KERN checkpoint 保存/恢复时会通知外部 runtime。社交平台 runtime 必须实现：

```python
save_checkpoint(context)
restore_checkpoint(context)
```

context 只包含同步身份：

```json
{
  "run_id": "...",
  "tick": 123,
  "time_str": "...",
  "phase": "save"
}
```

KERN 不传社交平台数据库路径，也不托管外部 runtime 文件。社交平台 runtime
用 `run_id/tick` 自己保存和恢复状态。

失败语义：

- 社交平台 save checkpoint 失败时，KERN checkpoint 也失败并中断。
- 社交平台 restore checkpoint 失败时，KERN runtime 启动失败。
- 不允许静默降级到不同步状态。

## 实现阶段

建议按以下顺序实现：

1. 扩展本文档并对齐契约。
2. 实现 SQLite social platform runtime 本体和单元测试。
3. 实现 `KERN/executor/_effect_social_platform.py` 和 effect contract。
4. 新增 `SocialAccountComponent` 或等价账号绑定组件。
5. 用 mock/小型数据验证 feed、post、interact、checkpoint restore 闭环。
6. 再接入 recipe/agent workflow 和 memory attention。

第一版不做：

- UI
- Web server
- 私信/通知
- 图片/视频
- 复杂 embedding 推荐
- 真实多用户并发服务
