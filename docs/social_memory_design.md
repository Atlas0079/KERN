# 社交平台 Agent 可见记录与记忆设计备忘

本文记录社交平台专用 Agent Workflow 的可见记录与记忆设计。它是设计备忘，不表示当前
代码已经实现。平台推荐、曝光和互动事实仍以 `social_platform_runtime_design.md` 为准；
当前社交 workflow 的执行计划仍以 `social_platform_experiment_plan.md` 为准。

## 设计动机

当前记忆链路主要围绕 `RecordInteraction` 展开：

```text
RecordInteraction
-> PerceptionComponent.interaction_inbox
-> workflow memory patch
-> ApplyMemoryPatch
-> MemoryComponent
```

这条链路适合记录“谁对谁执行了什么动作”，但不适合表达 Agent 在一个领域界面中的完整主观
经历。以社交平台为例，Agent 真正需要记住的不只是“我执行了 LikeSocialPost”，而是：

- 我打开推荐页时看到了哪些帖子；
- 每条可见帖子包含什么标题、正文、hashtag、原作者、直接转发者和公开互动计数；
- 我后来查看了哪条帖子全文；
- 我对哪条帖子点赞、评论或转发；
- 我的评论正文或转发语是什么；
- 这些经历发生在哪个 tick、哪次 feed session 和哪张曝光卡片之后。

这些信息属于 Agent 的可见经历，不应依赖通用 action narrative 去猜，也不应从全局 event log
自动注入。记录入口需要保持 Agent 可见性边界：只能记录 Agent 当时实际看到或实际执行成功的
内容。

## 目标

1. 推荐页本身可以完整进入 Agent 可见记录，包括当前页已经公开给 Agent 的帖子字段。
2. 后续查看帖子全文、点赞、评论和转发可以进入 Agent 可见记录，并保留对应帖子和操作细节。
3. 可见记录与 `EffectBundle` 事务一致；页面或操作回滚时，相关记录也回滚。
4. 可见记录先进入 inbox，由 workflow 统一决定是否、何时、以什么重要性写入 `MemoryComponent`。
5. 短期记忆不再按权重自动静默删除。短期队列满后，由 workflow 主动触发整理流程。
6. 整理流程保留最近一段时间的短期记忆，例如最近 5 tick 的内容暂不进入中期记忆。
7. 社交平台 workflow 使用领域专用 LLM 流程，不复用默认 Planner/Grounder。
8. 帖子标题、正文和操作细节进入 Agent 可见记录的机制应是通用能力，可被其他场景复用。

## 非目标

- 不把 KERN event log 自动作为 Agent memory。
- 不把平台排序分数、未展示候选、全网关注图、其他 Agent 私有画像写入记录或记忆。
- 不让 workflow 直接修改 `WorldState` 或 SQLite。
- 不把 `narrative_success` 扩展成所有记忆的唯一入口。
- 不引入 effect 之间的返回值传参或隐式临时参数总线。
- 不在当前阶段设计原创发帖、关注变更、平台通知或多页浏览策略。

## 当前问题

### `narrative_success` 不够用

`narrative_success` 适合一句动作叙述，例如“某人观察了某物”。社交平台需要记录的是一次界面
经历：推荐页包含多张卡片，每张卡片都有标题、正文、来源、标签和公开计数。它不是单个动作的
简单成功文本。

如果把所有内容都塞进 `narrative_success`，会出现几个问题：

- 页面的“看见”不是传统动作结果；
- 同一 effect 可能需要生成领域可见记录，而不只是展示文本；
- 不同领域需要不同记录粒度；
- 通用 interaction formatter 无法可靠还原领域细节；
- 审计日志、UI 叙述和 Agent 记忆会混成一个接口；
- 当前 `narrative_success` 在 action 执行前渲染，无法读取 effect 成功后写入的页面状态。

### `RecordInteraction` 和复杂经历不是两个层级

`RecordInteraction` 和原先候选的 `RecordExperience` 听起来像同一级别的机制：它们都表示
“向 Agent 暴露一条可被 workflow 处理的记录”。因此不应长期维护两条平行入口：

```text
RecordInteraction -> interaction_inbox -> workflow -> MemoryComponent
RecordExperience  -> short_term_queue
```

更合理的方向是把二者收敛成统一的 Agent 可见记录：

```text
world/domain effect 成功
-> 生成 Agent 可见 record
-> record_inbox
-> workflow memory policy
-> ApplyMemoryPatch
-> MemoryComponent
```

### 当前短期记忆会自动淘汰

`MemoryComponent.add_short_term()` 当前会按权重和衰减清理短期记忆，并把部分内容推入
`mid_term_prep_queue`。新的社交实验希望由 workflow 决定何时整理、整理哪些内容、哪些内容
保留在短期记忆里。

## 目标抽象：AgentRecord

引入统一的 Agent 可见记录概念，暂称 `AgentRecord`。它表达“某个 Agent 在当前事务中获得了一
段可被 workflow 处理的主观记录”。第一版只保留最小字段：

```json
{
  "record_id": "record_42",
  "tick": 12,
  "actor_id": "agent_001",
  "record_type": "social_action",
  "content": "我给标题是《海平面上升正在改变沿海生活》的帖子评论：这让我开始认真考虑沿海风险。"
}
```

第一版不要求 `source`、`data` 或 `tags`。重要性也不由 record 生成层决定；workflow 在把
record 写入 `MemoryComponent` 时再判断 importance、topic 和保留策略。

`record_type` 是基础类型，不是标签系统。它用于帮助 workflow 区分记录来源，例如：

- `interaction`
- `social_feed_view`
- `social_action`
- `dialogue`
- `tool_result`

如果第一版实现时希望进一步收缩，也可以只保存 `content`，但建议保留 `record_type`，否则
后续 memory policy 很难区分“页面浏览”“互动动作”和“对话”。

## Record Inbox

Agent 可见记录先进入 `PerceptionComponent` 的统一 inbox，建议字段名为 `record_inbox`：

```text
PerceptionComponent.record_inbox
-> workflow 读取并生成 memory patch
-> ApplyMemoryPatch(notes=[...], consume_record_ids=[...])
-> MemoryComponent.short_term_queue / mid_term_queue
```

这保持了与现有 `interaction_inbox` 相同的责任分工：

| 层 | 职责 |
| --- | --- |
| effect / recorder | 生成 Agent 已经可见的自然语言 record |
| PerceptionComponent.record_inbox | 暂存待 workflow 处理的可见记录 |
| workflow memory policy | 判断 importance、topic、是否写入记忆 |
| ApplyMemoryPatch | 原子写入 MemoryComponent，并消费 inbox |
| MemoryComponent | 保存正式短期与中期记忆 |

后续可以把 `RecordInteraction` 逐步折叠为 `AgentRecord(record_type="interaction")`。迁移期可以
保留 `interaction_inbox`，并让 memory policy 同时处理两个 inbox。

## Action / Bundle 级 `record`

旧的 `narrative_success` 应升级为 action 或 bundle 的一等 `record` 属性。`record` 不写成一个
普通 effect，而是告诉执行器：当前 bundle 成功后如何收集 Agent 可见记录。

候选形态：

```json
{
  "effects": [
    {
      "effect": "social_propagation:CommentOnVisiblePost",
      "terminal": "target",
      "post_id": "param:post_id",
      "text": "param:text"
    }
  ],
  "record": {
    "mode": "auto",
    "target": "self"
  }
}
```

`record.mode` 建议支持：

| mode | 语义 |
| --- | --- |
| `none` | 不生成 Agent 可见记录 |
| `auto` | 收集 bundle 中各 effect 成功后提供的 recorder 文本 |
| `template` | 使用 action/reaction 级整体模板，覆盖 effect fragments |

`record.target` 第一版使用 `self`，表示记录进入行动者自己的 `record_inbox`。后续如果需要广播给
其他 Agent，可以再设计显式 recipients；不要从 event log 自动推导。

## Effect Recorder

每个 `EffectSpec` 可以选择性提供一个 recorder 函数。世界写入仍由 handler 完成；recorder 只在
该 effect 成功后运行，用于生成自然语言 record fragment。

候选接口：

```python
def record_comment_on_visible_post(
    ws,
    data,
    context,
    events,
) -> str | list[str]:
    ...
```

输入含义：

- `ws`：effect 成功后的当前 `WorldState`；
- `data`：binder 规范化后的 effect 输入；
- `context`：执行上下文，包括 `self_id`、`target_id`、`parameters`、`action_id` 等；
- `events`：当前 effect handler 返回并封装前的事实列表，供 recorder 参考。

recorder 不执行世界写入，不调用外部 runtime，不触发新 effect。它只读取已经提交到当前事务内的
WorldState 和当前 effect 输入，返回自然语言文本。

这不是 effect 之间传递参数。前一个 effect 不把返回值传给后一个 effect。领域记录文本来自：

```text
规范化 effect 输入
+ action parameters
+ 当前 WorldState 中已经更新的可见状态
+ effect 自己的领域 formatter
```

### 社交评论示例

假设屏幕上的可见卡片为：

```json
{
  "post_id": "post_123",
  "title": "海平面上升正在改变沿海生活",
  "text": "过去十年，沿海社区已经更频繁地遭遇潮汐倒灌……",
  "original_author_id": "earth_voice",
  "position": 2,
  "comment_count": 8
}
```

Agent 提交 action：

```json
{
  "verb": "CommentOnSocialPost",
  "target_id": "phone_001",
  "parameters": {
    "post_id": "post_123",
    "text": "这让我开始认真考虑沿海风险。"
  }
}
```

recipe bundle：

```json
{
  "effects": [
    {
      "effect": "social_propagation:CommentOnVisiblePost",
      "terminal": "target",
      "post_id": "param:post_id",
      "text": "param:text"
    }
  ],
  "record": {"mode": "auto", "target": "self"}
}
```

`CommentOnVisiblePost` handler 成功后，recorder 读取同一个手机终端上的
`ScreenComponent.feed_items`，找到 `post_123` 的 `title`，并结合规范化输入中的评论正文：

```python
def record_comment_on_visible_post(ws, data, context, events):
    screen = _screen_from_terminal(ws, data["terminal_id"])
    card = _visible_card(screen, data["post_id"], _current_tick(ws))
    title = str(card.get("title", "") or "").strip()
    comment = str(data.get("text", "") or "").strip()
    if title:
        return f"我给标题是《{title}》的帖子评论：{comment}"
    return f"我给帖子 {data['post_id']} 评论：{comment}"
```

生成 record：

```json
{
  "record_id": "record_42",
  "tick": 12,
  "actor_id": "agent_001",
  "record_type": "social_action",
  "content": "我给标题是《海平面上升正在改变沿海生活》的帖子评论：这让我开始认真考虑沿海风险。"
}
```

该 record 进入 `agent_001` 的 `PerceptionComponent.record_inbox`。下一次 workflow 处理 inbox 时，
再决定它的重要性和记忆写入形式。

### 社交点赞和转发示例

点赞 recorder：

```text
我给标题是《海平面上升正在改变沿海生活》的帖子点了赞。
```

评论 recorder：

```text
我给标题是《海平面上升正在改变沿海生活》的帖子评论：这让我开始认真考虑沿海风险。
```

转发 recorder：

```text
我转发了标题是《海平面上升正在改变沿海生活》的帖子，并写道：沿海风险值得认真看。
```

如果帖子 schema 暂时没有 `title`，recorder 可以使用正文开头作为第一版 fallback：

```text
我给正文开头是“过去十年，沿海社区已经……”的帖子点了赞。
```

## 社交平台中的写入点

### 打开推荐页

`social_propagation:RefreshFeed` 成功后，如果 bundle 声明 `record.mode="auto"`，其 recorder 应生成
一次 `social_feed_view` record。内容来自手机 `ScreenComponent.feed_items`，也就是 Agent 已经实际
看到的公开卡片。

记录文本应包含：

- `feed_session_id`；
- 页面 tick；
- 每张卡片的标题或正文摘要；
- 可见 hashtag；
- `original_author_id`；
- `feed_item_kind`；
- `reposted_by_account_id` 和 `reposted_tick`；
- `source_kind` 和 `source_account_id`；
- 页面位置；
- 点赞、评论、转发计数；
- 当前查看者是否已经点赞或转发。

不得包含：

- 推荐排序分数；
- ranking topics；
- condition_id；
- 未展示候选；
- 全局平台指标；
- 其他 Agent 私有画像。

### 查看帖子全文

如果后续加入“进入帖子详情页”，详情页 recorder 应记录完整标题、正文、可见评论摘要或详情页
公开字段。第一版如果没有详情页，推荐页卡片标题和正文摘要就是可记录内容。

### 点赞、评论、转发

`LikeVisiblePost`、`CommentOnVisiblePost`、`RepostVisiblePost` 成功后，如果 bundle 声明
`record.mode="auto"`，各自 recorder 应生成一次 `social_action` record。内容来自当前屏幕中对应
`post_id` 的可见卡片和本次提交的操作参数。

记录示例：

```text
我评论了 earth_voice 标题是《海平面上升正在改变沿海生活》的帖子：这让我开始认真考虑沿海风险。
```

对于转发，应保存转发语；对于评论，应保存评论正文；对于点赞，应保存被点赞帖子的标题或摘要。

## 社交 workflow 新流程

社交平台专用 workflow 不使用 Planner/Grounder。它应包含两个领域 LLM 阶段：

1. `social_memory_consolidation`
2. `social_platform_page_decision`

建议流程：

```text
begin_turn
-> 读取 record_inbox / interaction_inbox
-> 将待处理 record 转成 memory patch
-> 检查短期记忆是否需要整理
   -> 若需要，调用 social_memory_consolidation
   -> 写入中期记忆
   -> 短期记忆达到 40 条时，按时间保留最新 10 条，其余整理进入中期记忆
-> 检查 activation schedule
   -> 未调度：EndTurn(reason="not_scheduled")
-> BrowseSocialFeed
-> RefreshFeed recorder 生成 feed view record
-> 构造社交专用 perception
   -> 身份组件
   -> 当前 ScreenComponent
   -> 短期社交记忆
   -> 中期摘要
-> 若实验帖不可见：EndTurn(reason="experimental_post_not_visible")
-> 调用 social_platform_page_decision
-> 提交 like/comment/repost action intents
-> 成功 effect recorder 生成操作 record
-> EndTurn
```

整理阶段不应读取全局平台事实，只处理 Agent 自己的 record inbox 和 memory 队列。

## 短期到中期记忆整理

新的整理策略由 workflow 触发，而不是由 `MemoryComponent` 自动按权重删除。

初始规则：

- `consolidation_trigger_entries = 40`；
- 短期队列达到 40 条时，workflow 触发整理；
- 按时间保留最新 10 条短期记忆；
- 剩余更早的短期记忆作为整理候选；
- LLM 只输出中期摘要和整理说明，不决定短期保留名单；
- 整理候选从 `short_term_queue` 删除；
- 中期记忆写入 `mid_term_queue`；
- 如果候选为空，workflow 不调用 LLM。

候选 consolidation 输出：

```json
{
  "mid_term_summaries": [
    {
      "summary": "我多次看到海平面上升相关内容，并对后果型叙事表现出较高关注。",
      "tick_start": 12,
      "tick_end": 18
    }
  ],
  "decision_summary": "整理了较早的社交平台浏览和互动经历。"
}
```

是否需要一个新的 effect，例如 `ApplyMemoryConsolidation`，待设计确认。也可以扩展
`ApplyMemoryPatch`，增加“删除指定 short-term record ids”的能力。

## 通用性要求

Agent 可见记录机制不应写死社交平台字段。其他场景也可以用 effect recorder 记录：

- 阅读一本书或一封邮件；
- 看到一个仪表盘结果；
- 接收外部 runtime 返回的页面；
- 观察到一个复杂场景状态；
- 完成一段工具调用并得到结构化结果。

领域 effect 负责基于当前可见状态构造 Agent-facing `content`。核心只负责事务内收集、写入
`record_inbox`、让 workflow 原子消费 inbox 并写入正式记忆。

## 待决问题

1. 统一记录概念命名使用 `AgentRecord`、`RecordExperience` 还是 `RecordPerception`？
2. `PerceptionComponent` 中新增 `record_inbox`，还是创建独立 `AgentRecordInboxComponent`？
3. `EffectSpec` recorder 字段命名与解析规则如何定义？
4. `record.mode="template"` 的模板渲染应使用哪个上下文，是否允许读取最终 `WorldState`？
5. `RecordInteraction` 是立即迁移为 recorder，还是先保留并让 memory policy 同时读取
   `interaction_inbox` 与 `record_inbox`？
6. `ApplyMemoryPatch` 是否扩展 `consume_record_ids` 和删除 short-term record ids，还是新增
   `ApplyMemoryConsolidation`？
7. 中期整理 LLM 输出错误是否终止 runtime？初步倾向与页面决策一样 fail-fast。
8. feed view record 是否保存完整 8 张卡片全文？当前需求倾向先生成可读摘要，避免第一版 checkpoint
   体积和 token 成本过高。
9. 记忆整理是否每个 turn 开始都检查，还是只在 scheduled active turn 中检查？当前实现是在
   active social turn 浏览页并消费新 record 后检查。

## 建议实施顺序

1. 固化统一 Agent 可见记录契约：`record_inbox`、`record_id`、`record_type`、`content`。
2. 扩展 `EffectBundle` 支持 `record` 字段，扩展 `EffectSpec` 支持可选 recorder。
3. 在 executor 中实现 `record.mode="auto"`：成功 effect 的 recorder 输出在同一事务内写入
   `PerceptionComponent.record_inbox`。
4. 扩展 `ApplyMemoryPatch` 和 memory policy：读取/消费 `record_inbox`，由 workflow 分配
   importance 并写入 `MemoryComponent`。
5. 修改短期记忆策略：停止权重自动淘汰，保留显式整理入口。
6. 为社交 `RefreshFeed`、`LikeVisiblePost`、`CommentOnVisiblePost`、`RepostVisiblePost` 增加 recorder。
7. 社交 workflow 增加 memory consolidation 阶段。
8. 增加 focused tests：
   - 推荐页完整生成 `social_feed_view` record；
   - 评论 record 使用当前卡片 `title` 和 action 参数中的评论正文；
   - 点赞和转发 record 进入 `record_inbox`；
   - bundle 失败时 record 回滚；
   - workflow 将 record 转入短期记忆并消费 inbox；
   - 最近 5 tick 不被整理；
   - 整理结果进入中期记忆；
   - 被整理旧短期记忆被删除；
   - 社交 LLM 决策能读取短期和中期社交记忆。
