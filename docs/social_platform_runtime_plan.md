# 社交平台外部 Runtime 计划

本文记录“仿社交媒体平台 runtime 接入 KERN”的当前设计。它是给 LLM agent 使用的外部信息环境，不需要 UI，也不面向真人用户操作。

当前方向是：社交平台 runtime 自己维护账号、帖子、推荐、曝光、浏览、互动和 checkpoint 状态；KERN 只通过明确的组件和 effect 暴露 agent 可执行动作。

## 当前取舍

第一版重点是让 agent 能在模拟里刷推荐流、点开帖子、发帖、点赞/评论/转发、关注账号，并让这些行为产生可观察事件和 memory hint。

暂时不做：

- 设备/app session 安全边界。
- 负反馈、拉黑、静音、不感兴趣。
- 通知、私信。
- UI、Web server。
- 图片/视频。
- 复杂 embedding 推荐。
- 真实多用户并发服务。

安全边界先保持很薄：agent 通过目标手机实体的 `ScreenComponent.runtime_id/account_id` 使用平台账号。后续如果出现越权、共享设备、伪造账号等问题，再升级到 `SocialAppComponent` / `DeviceAccessComponent` / session 校验。

## 已实现

当前代码已经有一个 SQLite-backed social platform runtime：

```text
KERN/external_runtimes/social_platform.py
```

已实现能力：

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

平台 runtime 当前维护这些 SQLite 表：

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

KERN 侧也已经有通用 bridge：

```text
KERN/external_runtime.py
```

`KernRuntime` 会把 `external_runtime_bridge` 注入 `world_state.services`，并在 checkpoint save/restore 时通知外部 runtime。

## KERN 内组件设计

第一版用一个正式屏幕组件承接 planner/grounder 和外部社交平台之间的上下文：

```text
ScreenComponent
```

建议文件：

```text
KERN/models/components/screen.py
```

它挂在手机、电脑或其他可操作终端实体上。第一版先设计一个手机实体：

```json
{
  "template_id": "Phone",
  "entity_name": "豆豆的手机",
  "components": {
    "TagComponent": {"tags": ["device", "phone", "social_media_terminal"]},
    "ScreenComponent": {
      "runtime_id": "weibo",
      "account_id": "acc_doudou",
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

建议字段：

```python
@dataclass
class ScreenComponent:
    runtime_id: str = "weibo"
    account_id: str = ""
    app: str = ""
    view: str = "blank"
    title: str = ""
    feed_items: list[dict[str, Any]] = field(default_factory=list)
    current_post: dict[str, Any] | None = None
    selected_post_id: str = ""
    cursor: int = 0
    updated_tick: int = 0
    status_text: str = ""
    last_event_type: str = ""
    last_error: str = ""
```

KERN 内的含义：

- `runtime_id` 指向 `external_runtime_bridge` 里的 adapter key。
- `account_id` 是外部社交平台 runtime 内的账号 ID。
- `view` 表示当前屏幕状态，例如 `feed`、`post`、`composer`、`blank`。
- `feed_items` 保存当前屏幕上可见的帖子卡片，包含 `post_id`、作者、摘要、标签、社交上下文等。
- `current_post` 保存当前打开帖子的完整可见内容和评论摘要。
- `selected_post_id` 保存最近选中的帖子，供后续评论、点赞、转发等 effect 默认使用。

这个组件不是平台数据库。它只保存“屏幕此刻显示了什么”。平台真实状态仍然属于 `SQLiteSocialPlatformRuntime`。

### Planner / Grounder 用法

agent workflow 分 planner 和 grounder 后，planner 和 grounder 应使用不同的信息层：

```text
social runtime state: 真实平台状态，KERN 不直接暴露给 planner/grounder
agent memory: 给 planner 的语义连续性，例如“刚才看到一个户外活动帖子”
phone ScreenComponent: 给 grounder 的短期可操作引用，例如 post_id、slot、current_post
```

planner 不应该依赖或输出原始 `post_id`。planner 只需要表达意图，例如“打开刚才推荐页第一条帖子”或“评论当前帖子”。grounder 负责把这个意图落到当前屏幕状态上：

```text
planner: 我想看看推荐页第一条帖子
grounder: 从手机 ScreenComponent.feed_items[0].post_id 取出 post_id
effect: ObserveSocialPost(target="phone", slot=0)
```

因此帖子 ID 不需要进入 agent 自己的记忆。agent 可以记住“我刚才看到一个户外活动帖子”，但下一步要点开、评论、点赞时，grounder 应优先从手机屏幕状态里取可操作对象。

### Grounder 屏幕上下文窗口

为了避免 grounder 长期拥有过期的 post ID，屏幕组件进入 grounder 上下文应该有时间窗口。第一版建议：

```text
grounder_screen_context_window_ticks = 2
```

如果 agent 在最近 2 tick 内执行过社交浏览类动作，grounder 上下文可以包含目标手机 `ScreenComponent` 的完整可操作状态：

- `feed_items[*].post_id`
- `current_post.post_id`
- `selected_post_id`
- `runtime_id/account_id`
- `cursor`

planner 上下文仍然只暴露语义摘要，不暴露 raw `post_id`。也就是说，同一块屏幕状态会被投影成两个不同接口：

```text
planner view:
- 推荐页上有一条“明天户外活动需要带水壶”的帖子，作者是老师。

grounder view, only if screen context is fresh:
- phone.feed_items[0].post_id = "post_001"
- phone.feed_items[0].summary = "明天户外活动需要带水壶。"
```

如果屏幕上下文过期，grounder 不应该继续使用旧 `post_id`。它应要求 planner 先重新观察推荐页或打开帖子。

第一版不做设备/app session 安全校验。只要 effect 能找到目标手机实体和它的 `ScreenComponent.runtime_id/account_id`，就允许调用外部 runtime。后续如果出现越权、共享设备、伪造账号等问题，再升级为 `SocialAppComponent`、`DeviceAccessComponent` 或 session 模型。

## Effect 设计

第一版新增一个领域 effect 文件：

```text
KERN/executor/_effect_social_platform.py
```

新增 effect 类型：

```text
ObserveSocialFeed
ObserveSocialPost
CreateSocialPost
InteractSocialPost
FollowSocialAccount
```

这些 effect 是薄接口。它们不直接操作 SQLite，不实现推荐算法，只做：

1. 解析目标手机实体，读取 `ScreenComponent`。
2. 读取 effect 参数。
3. 组装 payload/context。
4. 调用 `external_runtime_bridge.invoke(...)`。
5. 根据 runtime 返回事件更新手机屏幕状态。
6. 返回 social runtime 产生的 KERN event dict，并可追加 `ScreenUpdated` 这类 KERN 本地事件。

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

handler 映射：

```text
operation = observe_feed
payload = {
  "account_id": phone.ScreenComponent.account_id,
  "limit": limit,
  "tick": ws.game_time.total_ticks
}
```

返回事件来自 runtime：

```text
SocialFeedObserved
```

handler 同时把 `SocialFeedObserved.items` 写入 `phone.ScreenComponent.feed_items`，设置：

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

handler 映射：

```text
operation = observe_post
payload = {
  "account_id": phone.ScreenComponent.account_id,
  "post_id": post_id,
  "tick": ws.game_time.total_ticks
}
```

返回事件：

```text
SocialPostObserved
```

handler 同时把 `SocialPostObserved.post` 写入 `phone.ScreenComponent.current_post`，设置 `view = "post"` 和 `selected_post_id = post_id`。

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

handler 映射：

```text
operation = create_post
payload = {
  "account_id": phone.ScreenComponent.account_id,
  "text": text,
  "tags": tags,
  "tick": ws.game_time.total_ticks
}
```

返回事件：

```text
SocialPostCreated
```

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

`post_id` 可以显式传入；如果没有传，handler 使用和 `ObserveSocialPost` 相同的屏幕解析规则。

支持 action：

```text
like
unlike
comment
repost
```

handler 映射：

```text
operation = interact_post
payload = {
  "account_id": phone.ScreenComponent.account_id,
  "post_id": post_id,
  "action": action,
  "text": text,
  "tick": ws.game_time.total_ticks
}
```

返回事件：

```text
SocialPostInteracted
```

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

handler 映射：

```text
operation = follow_account
payload = {
  "account_id": phone.ScreenComponent.account_id,
  "target_account_id": target_account_id,
  "tick": ws.game_time.total_ticks
}
```

返回事件：

```text
SocialAccountFollowed
```

## Binder 规则

`_effect_social_platform.py` 应提供这几个 binder：

```text
_bind_observe_social_feed
_bind_observe_social_post
_bind_create_social_post
_bind_interact_social_post
_bind_follow_social_account
```

Binder 只做浅规范化：

- `target` 解析为目标手机/终端实体引用，默认可以用 recipe 的 `target_id`。
- `limit` 转成 int，默认 5，范围 1-20。
- `slot` 转成 int；`post_id` 可选，显式传入时去空白。
- `target_account_id` / `action` / `text` 去空白。
- `tags` 规范成字符串列表。
- 支持 `param:` token，以便 recipe 把用户命令参数传入 effect。

屏幕解析、账号解析和 post_id fallback 不要放在 binder 里，放在 handler 里，因为 binder 当前主要处理 effect payload 和 context，不应该读取复杂 world 语义。

## Handler 公共辅助

建议在 `_effect_social_platform.py` 内部放一个小辅助：

```python
def _screen_for_target(executor, ws, context, data, effect_name):
    phone, err = executor.require_entity(ws, context, "target", effect_name, "target")
    ...
```

它负责：

- 找到目标手机/终端 entity。
- 读取 `ScreenComponent`。
- 校验 `runtime_id` 和 `account_id` 非空。
- 从 `ws.services["external_runtime_bridge"]` 读取 bridge。
- 返回 `(phone, screen, runtime_id, account_id, bridge)`。

另一个小辅助负责从屏幕解析帖子：

```python
def _post_id_from_screen(screen, data, effect_name):
    ...
```

解析优先级：

1. `data.post_id`
2. `data.slot` 对应的 `screen.feed_items[slot].post_id`
3. `screen.selected_post_id`
4. `screen.current_post.post_id`

错误事件建议使用：

```text
SOCIAL_SCREEN_COMPONENT_MISSING
SOCIAL_RUNTIME_ID_MISSING
SOCIAL_ACCOUNT_ID_MISSING
SOCIAL_RUNTIME_BRIDGE_MISSING
SOCIAL_POST_NOT_ON_SCREEN
```

## Event 和 Memory Hint

社交平台 runtime 已经返回 event dict 和 `memory_hint`。

第一版 effect handler 不改写这些事件，只原样返回，并在同一 effect 内更新目标手机的 `ScreenComponent`。原因：

- 事件语义属于 social runtime。
- KERN handler 只是领域 effect 到 external runtime 的 adapter。
- 屏幕状态属于 KERN world，是 grounder 的可操作上下文。
- 后续 memory policy / memory_attention 再根据 `memory_hint`、事件内容、权重和时间衰减决定记忆保留多久。

推荐页曝光可以进入短期记忆，但默认低权重、快衰减：

```json
{
  "memory_hint": {
    "should_remember_by_default": false,
    "importance": 0.1
  }
}
```

进入短期记忆不代表会长期保留。短期记忆模块后续应是一个基于权重和时间的混合评分系统：每条记忆有初始重要性、当前权重、创建 tick、最近访问 tick 和衰减参数。评分过低的记忆会被清掉，推荐页曝光这类低权重事件通常只保留很短的 tick。

对于包含大量自然语言的事件，后续可以在启发式评分之后引入一个轻量 LLM 评估器。它只处理已经被粗筛选过的候选事件，用来修正模糊语义下的权重，例如某条帖子是否和 agent 当前目标、兴趣、关系或风险高度相关。

点开帖子、评论、转发、发帖、关注默认更容易进入记忆。

## 事务约束

KERN 的 `WorldExecutor` 可以回滚 `WorldState`，但第一版 `SQLiteSocialPlatformRuntime` 的写入不会自动参与 KERN bundle 回滚。因此第一版先采用保守约束，不立即设计 external transaction：

- 社交平台写操作尽量独立成单 effect bundle。
- `CreateSocialPost`、`InteractSocialPost`、`FollowSocialAccount` 不要和其他会失败的 world mutation 混在同一个 bundle 里。
- `ObserveSocialFeed`、`ObserveSocialPost` 虽然主要是观察，但也会写 exposure/view history，因此同样建议单独成 bundle。
- 如果必须组合多个动作，把社交平台 effect 放在 bundle 最后，降低“外部 runtime 已写入但 KERN world 回滚”的概率。

后续如果需要强一致性，再给 `external_runtime_bridge` 增加外部事务接口：

```text
begin_external_transaction(bundle_id)
invoke(...)
commit_external_transaction(bundle_id)
rollback_external_transaction(bundle_id)
```

## Recipe 使用形态

后续可以在场景 recipes 里加几条命令：

```json
{
  "verb": "刷推荐",
  "bundle": {
    "effects": [
      {
        "effect": "ObserveSocialFeed",
        "target": "param:target",
        "limit": "param:limit"
      }
    ]
  }
}
```

```json
{
  "verb": "看帖子",
  "bundle": {
    "effects": [
      {
        "effect": "ObserveSocialPost",
        "target": "param:target",
        "slot": "param:slot"
      }
    ]
  }
}
```

```json
{
  "verb": "评论帖子",
  "bundle": {
    "effects": [
      {
        "effect": "InteractSocialPost",
        "target": "param:target",
        "slot": "param:slot",
        "action": "comment",
        "text": "param:text"
      }
    ]
  }
}
```

## 推荐算法

当前 runtime 已实现轻量微博式推荐，不做 embedding。分数大致来自：

```text
score =
  2.0 * interest_match
+ 1.5 * follow_boost
+ 1.2 * freshness
+ 1.0 * engagement
+ 0.8 * author_affinity
+ 0.4 * exploration_bonus
- 2.0 * seen_penalty
```

推荐结果使用 `run_id/account_id/post_id/tick/cursor` 派生稳定噪声，保证同一上下文下可复现。

负反馈项暂时不做。

## Checkpoint

当前 social runtime 已实现：

```python
save_checkpoint(context)
restore_checkpoint(context)
```

context 需要：

```json
{
  "run_id": "...",
  "tick": 123,
  "time_str": "...",
  "phase": "save"
}
```

第一版用 JSON 快照保存平台表状态，存入 `checkpoint_snapshots`。恢复时按 `run_id/tick` 重建 social runtime 表。

KERN checkpoint save 失败或 social checkpoint save 失败时都应该中断；不允许静默降级到不同步状态。

## 初始化数据

仍需要一个初始化工具或脚本，把外部生成/采样的数据灌入 runtime：

- accounts
- account interests
- initial posts
- post tags
- optional seed comments / likes / follows

第一版可以先用普通 Python helper 直接调用：

```python
rt.upsert_account(...)
rt.invoke("create_post", ...)
rt.invoke("follow_account", ...)
```

后续再做更完整的采样和 LLM 扩写流程。

## 下一步

建议实施顺序：

1. 新增 `ScreenComponent`，接入 component imports、entity type union、world builder/checkpoint 序列化。
2. 新增一个手机实体模板，挂 `ScreenComponent`，里面保存 `runtime_id/account_id` 和当前屏幕内容。
3. 新增 `_effect_social_platform.py`，实现五个 binder/handler，并让 handler 在调用 runtime 后更新手机屏幕。
4. 更新 `EFFECT_SPECS`。
5. 为 effect handler 写单元测试：缺屏幕组件、缺 bridge、observe feed 更新屏幕、slot 打开帖子、create、interact、follow。
6. 增加一个小型场景/recipe smoke，让 agent 可以通过 recipe 操作手机刷推荐、点开第 N 条、评论当前屏幕帖子。
7. 更新 planner/grounder 约定：帖子 ID 优先来自 `ScreenComponent.feed_items/current_post/selected_post_id`，不是 agent memory。
8. 更新 memory policy，让 social events 按 `memory_hint`、权重和时间衰减进入短期记忆并自然遗忘。
9. 再考虑初始化数据生成工具。

## Config-declared runtime and seed status

The social runtime is now intended to be declared by runtime config, not only
manually attached by tests or app code. The config key is:

```text
EXTERNAL_RUNTIMES_JSON
```

It is a JSON object keyed by runtime id:

```json
{
  "social": {
    "type": "sqlite_social_platform",
    "db_path": "checkpoints/social_phone_smoke/social.sqlite3",
    "reset_db": true,
    "seed_json": "Data/SocialPhone/social_seed.json"
  }
}
```

Current implementation:

- `KernRuntime.from_config(...)` builds configured external runtime adapters
  before world restore/build.
- `sqlite_social_platform` creates a `SQLiteSocialPlatformRuntime`.
- `seed_json` is applied through `KERN.external_runtimes.social_seed`.
- Explicit `external_runtimes={...}` passed to `from_config(...)` can still
  override config-declared adapters for tests or app wiring.

The first independent scenario for this integration is:

```text
Data/SocialPhone/
runtime_config.social_phone.smoke.json
```

It contains one test agent, one phone with `ScreenComponent`, three recipes
(`BrowseSocialFeed`, `OpenSocialPost`, `CommentSocialPost`), and a seeded social
runtime. This scenario is deliberately separate from Camping/Farm so phone
behavior can be tested without pulling in survival gameplay.

Initial post generation is currently a lightweight deterministic seed module:

```text
KERN/external_runtimes/social_seed.py
```

Seed files support:

- `accounts`: platform accounts and interests.
- `posts`: explicit initial post rows.
- `post_generators`: repeated text rows expanded into deterministic post ids.
- `follows`: initial follow graph edges.

This module is the right place to add later sampling or lightweight LLM
expansion. The runtime itself should keep owning platform behavior; the seed
module should only prepare initial platform state.
