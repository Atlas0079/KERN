# 社交平台外部 Runtime 计划

本文记录当前关于“外部社交平台 runtime 接入 KERN”的设计方向。目标是让社交平台作为一个可以独立运作的外部系统存在，同时通过 KERN 的 bridge 服务被 agent 使用。

它是给 LLM agent 使用的外部信息环境，不需要 UI，也不面向真人用户操作。KERN 只需要知道 agent 做了什么社交平台动作、平台返回了什么可见信息、产生了什么事件和 memory hint；社交平台 runtime 自己维护账号、帖子、推荐、曝光、浏览、互动和 checkpoint 状态。

## OASIS 参考取舍

OASIS 的社交仿真架构可以作为参考：它把系统拆成 platform、agents、actions、recommendation system 和 simulation engine，并由平台维护帖子、评论、关系、行为 trace 和推荐缓存。

本项目只借鉴结构，不照搬复杂度：

- 借鉴：平台状态由平台 runtime 自己拥有；agent 通过动作空间与平台交互；推荐同时考虑兴趣、关注网络、热度和新鲜度。
- 不借鉴：不做 UI，不做大规模分布式服务，不做复杂 embedding/TwHIN 推荐，不把平台内部数据库暴露给 KERN。

参考：

- https://docs.oasis.camel-ai.org/overview
- https://arxiv.org/html/2411.11581v4
- https://github.com/camel-ai/oasis

## 边界

KERN 继续作为模拟内核：负责 world state、agent workflow、recipe、effect、reaction 和 checkpoint。社交平台 runtime 是外部应用系统，拥有自己的账号、帖子、评论、点赞、分享、关注关系、推荐算法、浏览记录和通知状态。

KERN core 只提供一个桥梁服务：`external_runtime_bridge`。每个外部 runtime 应该提供自己的领域组件和专用 effect，而不是使用一个万能外部调用 effect。

也就是说，接入一个社交平台 runtime 应该类似：

```text
SocialPlatformRuntime
+ SocialAccount / SocialApp 组件
+ ObserveSocialFeed effect
+ ObserveSocialPost effect
+ CreateSocialPost effect
+ InteractWithSocialPost effect
+ FollowSocialAccount effect
+ SocialPlatformAdapter
+ 社交平台自己的状态和推荐算法
```

属于社交平台领域本身的 effect 必须放在单独文件中，方便后续按领域启用，例如：

```text
KERN/executor/_effect_social_platform.py
```

组件不要求单独文件边界。第一版可以只需要一个账号绑定组件，用来说明某个 KERN agent 对应哪个平台账号和 runtime。

## Agent 动作

第一版社交平台动作保持很小：

- 观察推荐页：agent 查看推荐流，只看到轻量帖子卡片，例如标题、作者、标签、简短摘要。
- 观察具体帖子：agent 点开某个帖子，看到正文、评论摘要和更完整上下文。
- 对帖子操作：一个动作内部支持点赞、分享、评论。

推荐页应该像真实信息流一样维护 feed session。每个账号有 feed cursor 和曝光记录。每次观察推荐页返回下一批帖子，并记录这些帖子曾经出现在推荐页上，但不默认把每条曝光内容写入 agent 记忆。

## KERN-facing Capability Contract

KERN 不需要社交平台提供 UI、页面、HTML、数据库路径或原始 SQL 查询能力。KERN 需要的是稳定的动作能力和 LLM 可消费的信息返回。

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

返回事件必须是 KERN event dict，并且包含足够给 LLM agent 使用的摘要信息。返回内容应该是“agent 此刻看到了什么”，而不是数据库原始行。

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

推荐页曝光必须写入社交平台 runtime 的 exposure log，但默认不写入 agent memory。agent 是否记住某条推荐页曝光，由后续 memory attention 决定。

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

用途：agent 对帖子互动。第一版支持：

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

评论、转发、重要人物回复等事件可以给较高 `memory_hint`。普通点赞可以给低权重 hint。

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

## 社交平台状态

社交平台 runtime 至少需要保存：

- 用户/账号身份
- 帖子、评论、点赞、分享、关注关系
- 兴趣画像
- 推荐曝光记录和浏览历史
- 后续可加入私信和通知

浏览历史主要属于社交平台 runtime。agent memory 只保存 agent 真正注意到、互动过，或经过权重衰减后仍然重要的信息。

## SQLite-first Runtime

社交平台 runtime 第一版直接使用 SQLite，不做纯内存实现。SQLite 文件由 runtime 自己管理；KERN 不读取、不写入、不传入保存路径。

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

第一版可以用 JSON 快照保存全部平台状态，恢复时用该快照重建表。后续如果数据量变大，再改成增量 checkpoint 或 SQLite backup。

## 账号身份边界

agent 不应该直接把 `account_id` 作为可信参数传给社交平台 effect。账号身份应该由 KERN 根据 world state 证明，再交给外部 runtime 使用。

推荐链路：

```text
agent entity
-> target device entity
-> SocialAppComponent / DeviceAccessComponent
-> runtime_id + account_id + authenticated/session state
-> external_runtime_bridge
-> SocialPlatformAdapter
```

也就是说，agent 发起动作时指定自己要操作的对象实体，例如手机、电脑或其他终端。binder 负责检查：

- 目标实体是否有社交平台应用组件。
- 目标实体绑定的是哪个 `runtime_id` 和 `account_id`。
- 当前 agent 是否有权使用这个设备或这个 app session。
- app session 是否处于已登录、未过期、未锁定状态。

第一版可以先用 `CustomComponent` 表达设备和社交 app 状态，等字段稳定后再升级为正式 Python component。例如：

```json
{
  "SocialAppComponent": {
    "runtime_id": "social_default",
    "account_id": "acct_001",
    "authenticated": true,
    "owner_entity_id": "agent_001",
    "allowed_user_entity_ids": ["agent_001"]
  }
}
```

如果第一版暂时不建模设备实体，也可以新增一个轻量账号绑定组件作为过渡：

```json
{
  "SocialAccountComponent": {
    "runtime_id": "weibo",
    "account_id": "acc_doudou"
  }
}
```

推荐优先使用设备/app session 绑定，因为它更接近“agent 正在使用哪个世界实体”。轻量 `SocialAccountComponent` 只适合最小闭环阶段，后续应收敛到可验证的设备与 app session 模型。

effect 的输入应该类似：

```json
{
  "effect": "ObserveSocialFeed",
  "target": "phone",
  "limit": 5
}
```

而不是：

```json
{
  "effect": "ObserveSocialFeed",
  "account_id": "acct_001",
  "limit": 5
}
```

这样 KERN 证明的是“哪个 agent 正在使用哪个世界实体”，社交平台 runtime 证明的是“这个账号在平台内部是否存在、状态是否有效、能否执行对应平台操作”。

## 外部 Runtime Checkpoint

社交平台 runtime 的状态不应该完全塞进 KERN `WorldState`，否则平台内部的帖子、评论、曝光、推荐游标和浏览历史会污染模拟内核。但是它也不能完全独立地随意存档，否则恢复时很难证明 KERN world state 和社交平台状态来自同一个 tick。

推荐设计是让 KERN archive 成为主时间线，外部 runtime 作为 checkpoint participant 参与存档。KERN 在记录 checkpoint 时通知 bridge，bridge 再请求每个 external runtime 生成同 tick 的快照。

建议流程：

```text
KERN record checkpoint at tick T
-> bridge.prepare_checkpoint(run_id, tick=T, archive_dir=...)
-> each external runtime writes or prepares its own snapshot
-> external runtime returns snapshot_ref + state_hash + schema_version
-> KERN writes world snapshot/delta and records external snapshot refs
-> KERN calls commit_checkpoint(snapshot_ref)
```

如果 KERN archive 写入失败，或某个外部 runtime 准备失败，则调用：

```text
abort_checkpoint(snapshot_ref)
```

manifest 或 snapshot meta 中应记录外部 runtime 的快照引用，例如：

```json
{
  "tick": 120,
  "external_snapshots": {
    "social_default": {
      "snapshot_ref": "external/social_default/snapshot_000120.json.gz",
      "state_hash": "...",
      "schema_version": "social_platform.v1"
    }
  }
}
```

恢复时，KERN 先恢复自己的 world snapshot，再根据对应 tick 的 `external_snapshots` 恢复每个 adapter：

```text
KERN restore snapshot tick T
-> read external_snapshots from archive metadata
-> bridge.restore_checkpoint(runtime_id, snapshot_ref, expected_hash)
-> attach restored adapter state
```

如果第一版使用 SQLite runtime，`save_checkpoint(context)` / `restore_checkpoint(context)` 的 context 只需要包含同步身份：

```json
{
  "run_id": "...",
  "tick": 123,
  "time_str": "...",
  "phase": "save"
}
```

KERN 不传社交平台数据库路径，也不托管外部 runtime 文件。社交平台 runtime 用 `run_id/tick` 自己保存和恢复状态。

失败语义：

- 社交平台 save checkpoint 失败时，KERN checkpoint 也失败并中断。
- 社交平台 restore checkpoint 失败时，KERN runtime 启动失败。
- 不允许静默降级到不同步状态。

第一版外部 runtime 可以保存完整快照，不必一开始就实现 delta。社交平台状态虽然字段多，但结构清晰，完整快照更容易验证：

- accounts / profiles
- posts / comments
- likes / shares / follows
- feed sessions / cursors
- exposures / view history
- notifications

后续如果数据量变大，再考虑让外部 runtime 自己维护 snapshot + delta，但仍然由 KERN tick 和 archive manifest 统一索引。

### 与事务回滚的关系

checkpoint 对齐解决的是“恢复到同一个 tick”。它不自动解决“effect bundle 失败时外部 runtime 已经改了状态”的问题。

第一版可以采取保守约束：

- 社交平台 effect 尽量作为 bundle 的最后一步。
- adapter 在确认操作合法前不修改内部状态。
- adapter 返回错误时必须保证没有部分写入。

更严格的后续设计是让 bridge 支持外部事务参与：

```text
begin_external_transaction(bundle_id)
invoke(...)
commit_external_transaction(bundle_id)
rollback_external_transaction(bundle_id)
```

这样 KERN bundle 成功时才提交外部 runtime 的 pending changes；bundle 回滚时也能回滚外部 runtime。这个能力可以放在 checkpoint participant 之后实现。

## 初始化数据生成工具

社交平台需要两个独立实用工具：

- 生成社交平台初始化帖子。
- 生成社交平台用户/agent 的身份背景。

这两个工具可以完全独立于 KERN runtime 运行，输出 JSON 数据供社交平台 runtime 加载。它们可以使用 LLM，但 LLM 不应该负责决定总体分布。

核心原则：

```text
Population diversity comes from controlled sampling; LLM generation only realizes sampled identities into natural language.
```

也就是说：

- 分布、标签组合、稀有度、互斥规则、平台均值由采样器控制。
- LLM 只负责把已经采样好的结构化身份扩写成自然语言背景。
- 后处理检查负责发现重复、越界、违反标签事实或不符合平台均值的样本。
- 修正阶段只修正不合格样本，不重新生成全部人群。

### Agent 背景生成流程

推荐流程：

```text
1. 预设标签体系和采样分布
2. 采样生成结构化 agent 背景骨架
3. 用规则检查骨架是否满足分布、互斥、配额
4. 让 LLM 根据骨架补全自然语言背景
5. 做质量、重复度、一致性检查
6. 对不合格 agent 调用 LLM 修正
7. 输出最终可用 profiles
```

结构化骨架示例：

```json
{
  "agent_id": "agent_037",
  "age_group": "young_parent",
  "occupation": "kindergarten_teacher",
  "family_role": "mother",
  "interests": ["picture_books", "craft", "child_safety"],
  "personality": ["patient", "slightly_anxious"],
  "posting_style": "sharing_tip",
  "activity_level": "medium",
  "trust_level": "high",
  "social_role": "community_helper",
  "life_anchors": ["keeps old picture books", "often repairs classroom materials"]
}
```

LLM 扩写后示例字段：

```json
{
  "agent_id": "agent_037",
  "display_name": "...",
  "bio": "...",
  "background": "...",
  "speaking_style": "...",
  "typical_posts": ["...", "..."],
  "interaction_tendencies": {
    "likes_to_comment": true,
    "shares_practical_tips": true
  },
  "source_tags": {
    "age_group": "young_parent",
    "occupation": "kindergarten_teacher",
    "interests": ["picture_books", "craft", "child_safety"]
  }
}
```

### 为什么不能只靠 temperature

生成 100 个 agent 时，仅靠 LLM temperature 往往不够。常见问题包括：

- 背景趋同，很多角色都像同一种“普通热心用户”。
- 职业、兴趣、表达风格分布不受控。
- 稀有角色不稳定，要么缺失，要么过度戏剧化。
- 长批量生成时，LLM 容易重复前文模式。

因此多样性应该来自多层约束：

- 标签分布采样。
- 互斥规则，例如 `student` 与 `retired_worker` 不应同时出现。
- 稀有标签配额。
- 活跃度、信任度、发帖风格、兴趣标签的联合分布。
- 生活锚点，例如固定社区、家庭结构、工作节奏、长期兴趣。
- 每个 agent 的 `profile_seed_id`，用于稳定且可复现地生成差异。
- 生成后相似度检查和局部修正。

### 检查与修正

检查阶段至少包括：

- 必填字段是否完整。
- 是否违反原始 tags。
- 是否生成了和 tags 冲突的事实。
- 背景是否过度戏剧化，不像普通社交平台用户。
- 多个 agent 之间是否过于相似。
- 兴趣、职业、活跃度、发帖风格是否符合总体分布。
- 文本长度是否在目标范围内。

修正阶段应该把原始 skeleton、当前生成结果和检查失败原因一起交给 LLM，让它只改有问题的字段：

```text
请保留 source_tags 不变，只修正以下失败项：
- background 与 occupation 冲突
- speaking_style 和另外 6 个 agent 过于相似
- bio 过度戏剧化
```

### 初始化帖子生成流程

初始化帖子也应使用类似流程：

```text
1. 预设 topic、subtopic、tone、format、author_type、expected_engagement 分布
2. 采样帖子骨架
3. 分配作者账号
4. LLM 扩写标题、正文、标签和可选评论种子
5. 检查重复度、话题覆盖、风格均值和长度
6. 对不合格帖子局部修正
7. 输出 initial_posts.json
```

帖子骨架示例：

```json
{
  "post_id": "seed_post_012",
  "topic": "kindergarten",
  "subtopic": "picture_book_repair",
  "tone": "helpful",
  "format": "short_tip",
  "author_type": "teacher",
  "expected_engagement": "medium",
  "tags": ["kindergarten", "picture_books", "repair"]
}
```

工具可以先设计为三个命令，也可以由一个总命令串联：

```text
sample-agent-skeletons
expand-agent-profiles
validate-and-repair-profiles
```

以及：

```text
sample-initial-posts
expand-initial-posts
validate-and-repair-posts
```

## 推荐算法草案

可以先做一个轻量微博式推荐，不做 embedding。候选来源：

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

推荐结果应该可复现。第一版可以用 `run_id/account_id/tick/cursor` 派生随机种子，避免恢复后同一 tick 的推荐流漂移。

第一版不需要追求真实复杂度，只需要能产生合理的基于兴趣的浏览流，并留下足够的曝光记录供后续行为和算法使用。

## 记忆机制方向

社交平台会制造大量低价值观察。如果每条推荐页曝光都进入固定 tick 的短期记忆，agent 上下文会很快被污染。因此更通用的方向是升级 KERN 的短期记忆机制：从 FIFO/固定窗口改为“权重驱动的短期记忆队列”。

核心原则：

- Raw events are not memories.
- 只有 attention candidates 可以进入 agent memory。
- 事件层记录客观事实；agent workflow 负责决定某个 agent 是否在意这个事实。
- 事件生产者可以提供 `memory_hint`，但 `memory_hint` 只是提示，不是最终权重。

建议新增模块：

```text
KERN/agent_workflow/memory_attention.py
```

职责：

- 从 `event_delta` 和 `interaction_delta` 中过滤掉控制流事件、effect 内部细节和低价值机械事件。
- 将保留下来的记录转成 actor-specific memory candidates。
- 根据类别、关系、目标相关性、兴趣匹配、情绪强度、新颖性等因素打分。
- 对现有短期记忆应用衰减。
- 优先遗忘低权重记忆。
- 将高权重或 agent 显式保留的记忆放入 mid-term preparation。

### 事件粗分类

`memory_attention` 不应该为每一个 event type 编写独立算法。KERN 的事件类型不是封闭集合：代码内置 effect 会返回事件，场景数据也可以通过 `EmitEvent` 产生任意领域事件。因此第一版应该使用“类别级过滤 + 类别级评分”。

| 类别 | 主要来源 | 保留条件 | 默认权重 | 衰减 | 中期候选 | 例子 |
| --- | --- | --- | --- | --- | --- | --- |
| `self_action` | `interaction_log` | actor 是自己，行动成功且有叙事意义 | 0.45-0.65 | normal | 可选 | 我整理了玩具堆；我观察了推荐页 |
| `observed_action` | `interaction_log` | 其他 agent 的行动被自己看见，且同地点或和自己相关 | 0.30-0.55 | fast/normal | 通常否 | 老师修好了故事灯 |
| `self_observation` | 专用观察 effect / interaction | 自己主动观察到的结果 | 0.25-0.65 | fast/normal | 可选 | 看推荐页；点开帖子；检查绘本角 |
| `observed_observation` | interaction | 看见别人观察或检查某物 | 0.20-0.40 | fast | 否 | 老师查看玩具堆 |
| `task_outcome` | `TaskFinished` / `TaskFailed` / `TaskCancelled` / `TaskInterrupted` | 任务结果和自己相关，或发生在可见范围内 | 0.55-0.90 | normal/slow | 是 | 修好绘本；任务失败；任务被打断 |
| `social_interaction` | 对话、社交行为 | 直接对自己说话、自己参与、或重要关系人参与 | 0.55-0.85 | normal/slow | 是 | 老师对我说了一句话 |
| `communication` | 手机、私信、电话、通知 | 消息发给自己，或来自重要关系人 | 0.50-0.90 | normal/slow | 是 | 妈妈发来消息 |
| `external_platform_event` | 社交平台 runtime | feed 曝光、点开帖子、点赞、评论、分享、回复 | 0.08-0.90 | fast/normal/slow | 可选 | 推荐页曝光很低；重要回复较高 |
| `failure_or_interrupt` | failed interaction / workflow error / task interrupt | 自己失败、计划落地失败、任务被打断 | 0.65-0.90 | slow | 是 | 我想做某事但找不到目标 |
| `threat_or_loss` | 语义事件 / reaction / task result | 受伤、损坏、死亡、资源损失、危险环境 | 0.75-1.00 | slow | 是 | 故事灯坏了；有人受伤 |
| `discovery_or_gain` | 语义事件 / observation | 发现物品、获得资源、学到线索 | 0.55-0.85 | normal/slow | 是 | 找到贴纸补丁；看到有用教程 |
| `explicit_memory` | `AddMemoryNote` / workflow note | effect 或 agent 显式要求记住 | 使用输入 importance | slow | 是 | 我想记住这件事 |
| `environment_salient_change` | 语义环境事件 | 和当前位置、目标或安全相关的显著环境变化 | 0.35-0.75 | normal | 可选 | 天黑了；起雾了；门被堵住 |
| `ignored_internal_event` | runtime / executor / reaction | 控制流、进度、普通属性变化、内部调试事件 | ignore | - | 否 | `WorldTickAdvanced`、`AdvanceTick`、`TaskProgressed` |

### 默认忽略的 raw events

第一版应默认忽略这些 raw events，除非它们被 reaction 或专用 effect 转成更语义化的事件：

- `WorldTickAdvanced`
- `AdvanceTick`
- `TaskProgressed`
- `WorkerTick`
- `AgentControlTick`
- `MemoryPatched`
- `MemoryNoteAdded`
- `RandomBundleResolved`
- `QueryApplied`
- `ReactionTriggered`
- `ReactionApplied`
- 普通 `PropertyModified`
- 普通 `StatusAdded` / `StatusRemoved`
- 普通环境 tick / expire 事件

例外规则：如果属性或状态变化代表了可感知的语义事实，应由 reaction 产生一个更高层事件。例如不要让 agent 记住 `PropertyModified energy -5`，而是当体力低于阈值时产生 `ChildNeedsRest`，再由 attention 模块决定是否进入记忆。

### 评分策略

第一版使用启发式评分。后续可以引入混合式评分：

- heuristic scorer：快速、稳定、每 tick 可运行，负责默认分类和基础权重。
- async LLM scorer：只处理经过粗分类后的少量候选，用于模糊、高价值或需要语义判断的内容。

推荐公式方向：

```text
final_weight =
  base_weight
+ self_relevance
+ goal_relevance
+ interest_match
+ social_relation
+ emotional_weight
+ novelty
- age_decay
```

短期记忆条目可以包含：

```json
{
  "memory_id": "mem_...",
  "content": "...",
  "category": "self_observation",
  "importance": 0.42,
  "current_weight": 0.37,
  "decay_profile": "fast",
  "decay_rate": 0.12,
  "created_tick": 120,
  "last_accessed_tick": 120,
  "source": {"kind": "event_log", "seq": 88},
  "tags": ["social_feed", "craft"]
}
```

推荐页曝光可以进入短期记忆，但初始权重低、衰减快。点开帖子、评论、分享、重要人物回复、目标相关内容会保留更久。中期记忆整理可以后续异步完成。

## 下一步

先把社交平台 runtime 作为当前 repo 内的本地外部 runtime/package 实现，方便快速调整 adapter、组件、effect 和记忆策略。等接口稳定后，再考虑拆成独立项目。

建议实施顺序：

1. 扩展本文档并对齐契约。
2. 实现 SQLite social platform runtime 本体、最小状态模型、账号数据和推荐页浏览记录。
3. 实现 `KERN/executor/_effect_social_platform.py` 和 effect contract。
4. 新增 `SocialAccountComponent` 或手机/设备实体上的 `SocialAppComponent` 身份绑定，并在 binder 中验证 agent 使用权限。
5. 实现五个社交平台动作：观察推荐页、观察具体帖子、发布帖子、对帖子操作、关注账号。
6. 用 mock/小型数据验证 feed、post、interact、checkpoint restore 闭环。
7. 扩展 `external_runtime_bridge` 和 archive，让外部 runtime 作为 checkpoint participant 参与同 tick 存档与恢复。
8. 将社交平台事件通过 `memory_hint` 和 attention category 接入记忆机制。
9. 实现 `memory_attention.py` 的候选过滤和类别级启发式评分。
10. 升级 `MemoryComponent`，让短期记忆按权重和衰减维护，而不是纯 FIFO。

第一版不做：

- UI
- Web server
- 私信/通知
- 图片/视频
- 复杂 embedding 推荐
- 真实多用户并发服务
