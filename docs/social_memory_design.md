# 社交平台 Agent 可见记录与记忆设计

本文描述当前实现。平台推荐、曝光和互动契约见 `social_platform_runtime_design.md`，
实验条件与运行配置见 `social_platform_experiment_plan.md`。

## 责任边界

世界操作、可见记录和长期保存的记忆各有自己的职责：

```text
ActionIntent -> recipe -> EffectBundle -> WorldExecutor
-> effect handler 更新页面或平台状态
-> effect recorder 生成当前用户可见的文字
-> PerceptionComponent.record_inbox
-> 应用层 workflow 生成 memory patch
-> ApplyMemoryPatch -> MemoryComponent
```

决策与 workflow 不直接修改 WorldState 或 SQLite。EffectBundle 提交前发生错误时，
世界状态和该事务内写入的 inbox 一起回滚。SQLite 写入经过外部运行时的事务适配器。
Event log 和完整 LLM trace 是审计证据，不会自动成为 Agent 记忆。

当前页面是决策时独立构造的上下文；inbox 暂存待处理的观察，MemoryComponent 保存
已被 workflow 接收的经历。消费观察而不新增 note 表示忽视，并不要求每条观察都被记住。

## 可见记录契约

Executor 统一生成 `record_type="effect_record"`，保留来源 effect，领域分类由应用负责。
例如一条成功评论产生的原始记录：

```json
{
  "record_id": "record_42",
  "tick": 12,
  "actor_id": "agent_001",
  "record_type": "effect_record",
  "source_effect": "social_propagation:CommentOnVisiblePost",
  "content": "我给标题是《海平面上升正在改变沿海生活》的帖子评论：这让我开始认真考虑沿海风险。"
}
```

记录进入行动者的 `PerceptionComponent.record_inbox`。现有 `interaction_inbox` 继续
保存 RecordInteraction 的观察；memory policy 同时处理两个 inbox，不合并或替换接口。

Bundle 的 `record` 配置支持 `mode="none"` 和 `mode="auto"`。`auto` 收集成功 effect
的 recorder 文本，并通过 `target="self"` 写入行动者的 inbox。`template` 未实现，配置时
明确报错。未定义广播 recipients，也不从世界事件推导接收者。

```json
{
  "effects": [{
    "effect": "social_propagation:CommentOnVisiblePost",
    "terminal": "target",
    "post_id": "param:post_id",
    "text": "param:text"
  }],
  "record": {"mode": "auto", "target": "self"}
}
```

EffectSpec 的 recorder 接收 handler 成功后的世界状态、规范化输入、执行上下文和结果事实，
返回字符串或字符串列表。它只构造可见经历，不进行写入，不调用外部运行时或其他 effect。

## 社交页面的记录

推荐流卡片包含标题、公开来源、标签和互动计数，不含正文与评论。RefreshFeed recorder
读取当前 ScreenComponent.feed_items，记录 feed session 和实际展示的卡片。

OpenPostDetail recorder 记录点开的帖子标题；页面全文和公开评论由详情页决策上下文提供。
当前 recorder 不把详情全文复制进长期记忆。BackToFeed recorder 记录返回推荐页。
点赞、评论、转发 recorder 读取当前详情页及本次参数，保存对应标题和评论正文或转发语。

这些记录不能包含排序分数、未展示候选、全网关注图、其他 Agent 私有画像或全局指标。
当前帖子 schema 必须提供非空标题，生成输入不能依赖旧版无标题格式。

## 应用层记忆分类

`applications/social_experiment/memory.py` 复用通用 memory patch 构造器，按明确的
`source_effect` 设置记忆类型与重要性：

| 来源 effect | 记忆类型 / topic | importance |
| --- | --- | --- |
| social_propagation:RefreshFeed | social_feed_view | 0.65 |
| social_propagation:LikeVisiblePost | social_action | 0.8 |
| social_propagation:CommentOnVisiblePost | social_action | 0.8 |
| social_propagation:RepostVisiblePost | social_action | 0.8 |

其余 effect record 沿用通用分类和 0.7 权重。内核不按社交 effect 名称猜测领域类型。
`ApplyMemoryPatch` 在同一个世界事务中写入 notes、消费观察 ID，并执行指定的短期删除
和中期摘要写入。notes 与 consume IDs 不要求一一对应。

## 决策与整理流程

应用层 SocialPlatformWorkflow 实现现有 AgentWorkflow / AgentTurnSession 协议。
未调度的 turn 不调用社交 LLM，也不提交浏览 effect。调度后的 turn 依次：

1. 通过 BrowseSocialFeed 打开推荐页。
2. 在准备页面决策前消费本人的观察，检查是否需要整理记忆。
3. 使用身份组件、当前屏幕和本人的近期社交记忆构造决策上下文。
4. 推荐流决策选择是否打开帖子，详情页决策选择点赞、评论、转发或空互动。
5. 成功操作的反馈到达后消费新记录；详情互动结束后通过 BackToSocialFeed 返回推荐页。
6. 每 turn 最多打开三条详情，完成或遇到拒绝反馈后结束 turn。

身份包含原始画像、大五人格及平台主要好友类别。好友类别是角色设定，不建立实际关注边。
默认决策上下文读取中期和短期队列末尾共 20 条，不包含其他用户的记忆。

短期队列达到 40 条时，workflow 按 tick 与队列顺序保留最新 10 条，将更早的条目提交给
`social_memory_consolidation`。候选为空时不调用 LLM。模型输出：

```json
{
  "mid_term_summaries": [{
    "summary": "我近期浏览了一些气候议题，也记录了自己对帖子的互动。",
    "tick_start": 12,
    "tick_end": 18
  }],
  "decision_summary": "整理了较早的浏览和互动经历。"
}
```

保留与删除名单由 workflow 确定，模型只生成摘要。现有 ApplyMemoryPatch 将候选记录 ID
从短期队列删除并写入中期摘要，无新增整理 effect。请求或输出校验失败会产生 failure
及 trace 证据并终止该次运行，不静默丢弃候选记忆。

## 验证与实验范围

工程检查验证记录来源、可见性、事务回滚、记忆消费及整理调用；它们不能证明模型行为
符合真人。统一首次阅读的单页决策测试使用空记忆，不运行上述浏览、操作或整理流程。
单页测试的输出协议与正式工作流应按各自实际请求报告，不以单页测量宣称传播实验完成。
