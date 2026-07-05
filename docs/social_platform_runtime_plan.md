# 社交平台外部 Runtime 计划

本文记录当前关于“外部社交平台 runtime 接入 KERN”的设计方向。

## 边界

KERN 继续作为模拟内核：负责 world state、agent workflow、recipe、effect、
reaction 和 checkpoint。社交平台 runtime 是外部应用系统，拥有自己的账号、
帖子、推荐算法、浏览记录、互动规则和通知状态。

KERN core 只提供一个桥梁服务：`external_runtime_bridge`。每个外部 runtime
应该提供自己的领域组件和专用 effect，而不是使用一个万能外部调用 effect。

## Agent 动作

第一版社交平台动作保持很小：

- 观察推荐页：agent 查看推荐流，只看到轻量帖子卡片，例如标题、作者、标签、
  简短摘要。
- 观察具体帖子：agent 点开某个帖子，看到正文、评论摘要和更完整上下文。
- 对帖子操作：一个动作族内部支持点赞、分享、评论。

推荐页应该像真实信息流一样维护 feed session。每个账号有 feed cursor 和曝光
记录。每次观察推荐页返回下一批帖子，并记录这些帖子曾出现在推荐页上，但不
默认把每条曝光内容写入 agent 记忆。

## 社交平台状态

社交平台 runtime 至少需要保存：

- 用户/账号身份
- 帖子、评论、点赞、分享、关注关系
- 兴趣画像
- 推荐曝光记录和浏览历史
- 后续可加入私信和通知

浏览历史主要属于社交平台 runtime。agent memory 只保存 agent 真正注意到、
互动过，或经过权重衰减后仍然重要的信息。

## 推荐算法草案

可以先做一个简化的微博式推荐分数：

```text
score =
  interest_match
+ author_affinity
+ freshness
+ engagement
+ exploration_bonus
- negative_feedback
```

第一版不需要追求真实复杂度，只需要能产生合理的基于兴趣的浏览流，并留下
足够的曝光记录供后续行为和算法使用。

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

## 下一步

先把社交平台 runtime 作为当前 repo 内的本地外部 runtime/package 实现，方便
快速调整 adapter、组件、effect 和记忆策略。等接口稳定后，再考虑拆成独立项目。
