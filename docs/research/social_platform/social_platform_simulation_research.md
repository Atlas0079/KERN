# 社交平台传播仿真：规模、网络与推荐机制调研

> 调研日期：2026-08-01
> 范围：社交媒体多智能体仿真的公开一手材料，以及其对 KERN 风险叙事实验的直接启示。

## 结论

100 个 Agent 不足以支持“平台规模”或真实总体传播率的外推，但足以完成第一阶段的**机制验证**：在固定、可审计的关注网络内，比较两种风险叙事经由“曝光 -> 决策 -> 转发 -> 新曝光”产生的相对扩散轨迹。

不应靠简单复制 100 个画像来宣称规模扩大。先固定机制和测量，再以网络规模、网络结构和随机种子为实验因素做稳健性检验。推荐流中，转发是新的候选传播来源；已经曝光的原帖则应被硬过滤，不能再因新的转发者而重复进入同一账号的 feed。

## 一手项目的可借鉴点

| 项目 | 公开的一手能力 | 对 KERN 的具体启示 |
|---|---|---|
| [OASIS](https://github.com/camel-ai/oasis) / [论文](https://arxiv.org/abs/2411.11581) | 官方 README 声明最高 100 万 Agent、23 类动作（含关注、评论、转发）和兴趣/热度推荐；其 [推荐文档](https://github.com/camel-ai/oasis/blob/main/docs/key_modules/recommendation_system.mdx) 明确列出 `RANDOM`、Twitter、TwHIN、Reddit 等策略。 | 大规模能力与本实验的因果识别是两件事。借鉴其“平台环境 + 动作 + graph + step”分层，先实现可检查的 `recommend -> expose -> interact` 闭环，并把随机推荐作为对照条件。 |
| [AgentSociety](https://github.com/tsinghua-fib-lab/AgentSociety) / [论文](https://arxiv.org/abs/2502.08691) | v1 提供城市级 Ray 分布式与 gRPC 环境接入；当前 README 对 v2 强调模块化环境工具、JSONL replay 与 DuckDB trace。 | 平台 runtime 应与 Agent 执行器分离，并保存可回放事件。官方材料未给出微博式推荐/转发算法，不把它作为本平台的机制依据。 |

上述项目说明“很多 Agent”是可工程化的，但没有提供一个可直接替代研究设计的统一人数阈值。OASIS 的百万级主张是平台吞吐能力；其 README 同时给出了 100 Agent、一步、全量激活的 LLM token 成本示例，反而说明激活频率与人数必须作为显式实验参数。

## 推荐与转发的最小语义

令原帖为 `P`，账户 A 转发 `P`，账户 B 关注 A。B 在后续 tick 的候选卡片是同一个 `post_id=P`，但携带传播来源：

```text
feed item = { post_id: P, kind: "repost", source_account_id: A,
              original_author_id: P.author_id, source_tick: repost.created_tick }
```

候选来源仅包括“关注的原作者发布”与“关注者转发”。同一原帖可能有多个来源，但一个 feed 页最多一张卡片；排序时保留得分最高的来源。`exposures(account_id, post_id)` 是硬排除条件：B 一旦已曝光 P，P 不再进入 B 的后续候选集合。曝光本身不增加或减少分数。

建议把来源与排序分开：

```text
candidate score = interest_match(P, B)
                + follow_source_boost(A or original author, B)
                + recency(source event)
                + observable engagement(P)
```

其中 `source event` 对原帖候选为发帖、对转发候选为转发。这样转发提高的是“关注该转发者的用户看到该帖的机会”，而不是无条件抬高全站热度。点赞与评论可进入 `observable engagement(P)`，但不应取代具体的关注传播边。为识别推荐机制本身的影响，应增加一个不使用兴趣、关注和互动的 `random` 排序对照；OASIS 也将随机推荐作为可选策略。

## 人数与网络的建议

### 第一阶段：保留 100 个异质 Agent

使用已保留的 100 个画像和 1,900 条关注关系，完成两类叙事的重复运行。1,900 / 100 = 19，平均每个账户约有 19 条有向关注边，足以产生多跳扩散；但应报告实际入度、出度、连通分量和聚类系数，不能只报告人数。

每个条件至少跨多个随机 seed 重跑，并固定同一网络和共同随机数以配对比较叙事。输出每 tick 的首次曝光数、当 tick 转发数、累计转发数、级联深度、首次触达来源占比，以及多次运行的均值和区间。结果表述限定为“该已定义网络与决策模型下的机制差异”。

### 第二阶段：结构稳健性，而非直接复制人口

在不改 Agent 决策契约的前提下，增加合成网络条件，例如：

- 保留原网络；
- 与原网络节点数、度分布相同的随机重连网络；
- 保留社群但提高/降低跨社群边比例的网络；
- 以 200、500、1,000 个节点逐级扩展的合成网络。

扩展节点必须有明确生成规则：从已有人格画像的经验分布抽样、以分层配额复制，或另行生成并标记为合成。网络、画像分配和所有随机源都应由实验 seed 派生并归档。只有当不同规模和结构下的结论方向稳定时，才能讨论机制对规模的敏感性。

## 对 KERN 的实施建议

1. 保持 SQLite runtime 的确定性：`recommend_feed` 只读，`record_exposure`、`like`、`comment`、`repost` 是显式写操作。
2. 转发只写 `reposts(account_id, post_id)`，不复制原帖；feed 卡片记录 `source_account_id`，曝光也记录同一来源。
3. 加入点赞、评论和转发，但首个主要因变量仍设为“首次曝光后的转发”。点赞/评论可作为可见互动信号和次要结果，避免一开始让三类行为共同驱动复杂反馈。
4. 将 `population/network/recommendation/narrative/activation/seed` 纳入 study config，并把每轮 feed 候选、最终曝光、互动和指标写入 archive。
5. 在完成 100 人闭环及其回归测试前，不引入百万级目标或实时 LLM 全员逐 tick 调用；后者会混淆计算预算、调度假设和传播机制。

## 来源与边界

- Yang et al., [OASIS: Open Agent Social Interaction Simulations with One Million Agents](https://arxiv.org/abs/2411.11581), 2024；[官方仓库](https://github.com/camel-ai/oasis)。
- POSIM authors, [POSIM: A Multi-Agent Simulation Framework for Social Media Public Opinion Evolution and Governance](https://arxiv.org/abs/2603.23884), 2026；[官方仓库](https://github.com/DeepCogLab/posim)。
- Piao et al., [AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents Advances Understanding of Human Behaviors and Society](https://arxiv.org/abs/2502.08691), 2025；[官方仓库](https://github.com/tsinghua-fib-lab/AgentSociety)。

本文仅据上述论文和官方仓库的公开描述提出工程与实验设计建议；它们不证明 100 人模型可以外推到真实平台，也不把模拟结果当作现实世界的因果估计。
