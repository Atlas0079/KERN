# 社交传播基础包、SU7 与微塑料场景包设计

> 状态：待实现设计。本文定义可复用的社交传播基础能力包 `SocialPropagationBase`，以及两个依赖它、可独立运行的世界包：`SU7SocialPropagation` 与 `MicroplasticNarrative`。本文取代“在旧 SU7 社交调度上叠加微塑料实验”的方案。

## 1. 决策

社交传播采用唯一的会话模型。agent 不再由 `SocialActivityGateTick` 获得一次泛化 action 机会；每个被选中的 agent 在一个 round 中完成一次有限的社交会话。SU7 与微塑料只能以场景数据改变会话参数、内容和研究口径，不能各自实现行动循环。

```text
runtime config
├─ Packages/SocialPropagationBase       capability package
└─ 一个 world package（恰好一个）
   ├─ Packages/SU7SocialPropagation
   └─ Packages/MicroplasticNarrative
```

这与当前 Package 组合规则一致：每次运行恰好选择一个 world package，并可选择能力包。基础包不提供 World、Entities 或 Reactions；它通过扩展提供 effect 和通用社交 recipes。两个下游包各自拥有完整的世界数据、reaction、seed、配置和 checkpoint identity。

## 2. 目标与非目标

基础包负责：推荐页曝光、阅读、导航、终局互动、会话预算、稳定调度、并行决策/串行提交和审计语义的一致性。

基础包不负责：现实平台人口规模、心理状态、文本真实性判断、情绪分类、SU7 的事故叙事、微塑料的因果结论或统计推断。

`WorldState` 不保存帖子和互动表；SQLite social runtime 继续保存平台事实。`ScreenComponent` 仅是当前可见页面的世界内投影。workflow、recipe 和 reaction 均不得直接写 SQLite 或 `WorldState`。

## 3. 包结构与加载

### 3.1 基础 capability package

```text
Packages/SocialPropagationBase/
├─ kern-package.json
├─ extensions.py
├─ effects/social_session.py
├─ Data/Recipes.json
└─ Data/Bundles.json                 # 可选：仅通用命令 bundle
```

manifest 的 `provides_world` 为 `false`。它的 extension 注册带命名空间的 effects：

```text
social_propagation:SocialSessionRound
social_propagation:ExitSocialSession
social_propagation:DeliverSocialPost
```

`SocialSessionRound` 是外部 seam：scenario reaction 只需声明一次 round；候选筛选、稳定随机、屏幕刷新、步骤循环、命令资格、预算、审计和失败处理全在这个深模块内部。

当前 Package loader 只读取 world package 的 recipes/bundles。为使基础包真正成为通用命令的唯一来源，需要扩展 Package data composition：能力包可声明 `recipes` 与 `bundles`，loader 按 config 顺序先合并能力包、再合并 world package。同名 recipe/bundle ID 必须报错，不能覆盖。能力包不能声明 `world`、`entities` 或 `reactions`，因此不会偷偷创建世界或调度行为。

### 3.2 下游 world packages

```text
Packages/SU7SocialPropagation/
├─ kern-package.json
└─ Data/{World,Entities,Reactions,Bundles,social_seed,scenario_meta}.json

Packages/MicroplasticNarrative/
├─ kern-package.json
└─ Data/{World,Entities,Reactions,Bundles,social_seed,scenario_meta}.json
```

两者的 runtime config 都显式选择 `SocialPropagationBase`，再选择自身为 `world: true`。世界包的 `Reactions.json` 只在 `WorldTickAdvanced` 上调用一次 `social_propagation:SocialSessionRound`；它不复制基础 recipes 或效果实现。

## 4. 会话状态机

一个 tick 是否等于现实时间由 world package 说明；基础包只把它视为可排序的 round 编号。

```text
eligible → selected → initial-feed → deciding
                                  ↓
                    navigate (feed/open) → deciding
                                  ↓
          terminal / agent-exit / budget-exhausted / failure → ended
```

每位 selected agent 每 round 至多有一个会话。会话不跨 tick 保存执行中的 Python 状态，因此 checkpoint 只需保留已提交的平台事实与屏幕投影。

| 状态转换 | 发起者 | 平台/世界结果 |
| --- | --- | --- |
| `selected → initial-feed` | 调度器 | `ObserveSocialFeed` 写 exposure 并更新 `feed_items` |
| `deciding → navigate` | workflow | `ContinueBrowsing` 或 `OpenSocialPost` |
| `navigate → deciding` | 调度器 | 成功提交后更新预算和屏幕，再请求下一步决策 |
| `deciding → terminal` | workflow | like、comment、repost 或原创发帖，成功后结束 |
| `deciding → agent-exit` | workflow | `ExitSocialSession` 事件，结束且无互动 |
| 任意活跃状态 → budget-exhausted | 调度器 | 写会话结束记录 |
| 任意活跃状态 → failure | 执行器/契约 | 写错误与会话结束记录，后续 agent 继续 |

## 5. 命令、资格与效果

基础 recipes 提供以下中性命令；旧 `rumor_*` recipe 名称不存在。

| 命令 | 类别 | 前置条件 | effect |
| --- | --- | --- | --- |
| `ContinueBrowsing` | 导航 | 尚有 feed 页预算 | `ObserveSocialFeed` |
| `OpenSocialPost` | 导航 | 当前新鲜 `feed_items` 中可解析的卡片；尚有打开预算 | `ObserveSocialPost` |
| `LikeSocialPost` | 终局 | policy 指定为卡片层或已读层 | `InteractSocialPost(action=like)` |
| `CommentSocialPost` | 终局 | 当前 `current_post` 是本会话已打开帖子 | `InteractSocialPost(action=comment)` |
| `RepostSocialPost` | 终局 | 当前 `current_post` 是本会话已打开帖子；账号未转发该帖子 | `InteractSocialPost(action=repost)` |
| `CreateSocialPost` | 终局 | policy 允许；文本通过既有 binder | `CreateSocialPost` |
| `ExitBrowsing` | 终局 | 无 | `social_propagation:ExitSocialSession` |

`SocialSessionRound` 在执行前检查命令类别和会话预算；各社交 binder 仍验证实体、屏幕、帖子和文本。SQLite runtime 为 repost 增加 `(account_id, post_id)` 唯一约束，并返回幂等结果，作为最后一道数据完整性保障。

每个实际外部平台操作保持独立 effect bundle。外部 SQLite 写入不属于世界事务，不能放入与其他易失败世界写入混合的 bundle。

## 6. `SocialSessionRound` interface 与 policy

reaction 的 interface 不使用尚不存在的 `policy_id` 查找机制。全部场景参数以一个受 binder 验证的、声明式 `policy` 对象提供；它是调用者必须知道的完整配置，而不是 workflow 自由文本。

```json
{
  "effect": "social_propagation:SocialSessionRound",
  "provider_id": "social_llm",
  "max_agents_per_round": 100,
  "decision_mode": "parallel_decide_serial_commit",
  "max_decision_workers": 30,
  "policy": {
    "selection": {
      "kind": "social_behavior_rate",
      "base_rate_multiplier": 1.0
    },
    "session": {
      "initial_feed_limit": 8,
      "max_feed_pages": 3,
      "max_open_posts": 2,
      "max_terminal_actions": 1
    },
    "permissions": {
      "allow_create_post": true,
      "like_requires_open_post": false,
      "comment_requires_open_post": true,
      "repost_requires_open_post": true
    }
  }
}
```

v1 只支持两个显式选择 adapter：

- `social_behavior_rate`：world 的结构化社会活动参数决定启动概率；SU7 使用它；
- `big_five_extraversion`：`clamp(alpha + beta_e × extraversion)`；微塑料使用它。

每个 adapter 都以 `run_id|tick|agent_id|adapter_id` 哈希生成稳定 roll。选择 adapter 是真实可变点，故它是基础模块的内部 seam；不得在 scenario handler 中重新实现筛选循环。未知 adapter、缺失参数、负预算、未知 permission 或不支持的决策模式在 binder 阶段失败。

## 7. 并行与确定性

一个会话的下一步依赖上一提交后的屏幕，不能提前并行计算。round 因此按“决策层”执行：

1. 以稳定 agent ID 顺序，为全部 selected agent 串行刷新初始 feed；
2. 为仍在会话中的 agent 准备上下文和 memory patch；
3. 该层的 `workflow.decide(...)` 可并行；
4. 以稳定 agent ID 顺序验证并提交每一个命令；
5. 对执行导航的 agent 进入下一层，直至全部结束或预算耗尽。

此顺序让 LLM 调用并行，同时让 exposure、推荐输入、互动计数、屏幕更新、事件和 SQLite 写入保持可复现的串行顺序。prepare 阶段不得写平台或世界状态；memory patch 是既有世界 effect，必须在每个 agent 的提交顺序中应用。

## 8. 审计与导出契约

新增或规范化 `social_session_traces`（SQLite 表或等价的 action trace schema），每个会话至少记录：

```text
run_id, session_id, account_id, agent_id, tick,
selection_adapter, selection_probability, stable_roll,
step_index, pages_opened, posts_opened,
command, target_post_id, outcome, exit_reason
```

平台事实仍使用既有表：`exposures`、`view_history`、`likes`、`comments`、`reposts`、`posts` 与 `action_traces`。导出工具应以这些事实表为主，以会话 trace 解释机会、导航与退出；不得从 LLM 文本推断阅读或互动。

## 9. 旧路径的删除范围

迁移为原子替换，不保留兼容分支、开关或旧数据：

- 删除 `SocialActivityGateTick` 的 binder、handler、core catalog 注册和测试；
- 删除 `social_action_cooldown` 与所有 recipes 中附带的 `AddStatus`；
- 删除 `social_activity_opportunity`、`rumor_experiment` 等旧 workflow context；
- 删除 `rumor_*` recipes 及其 scenario prompt 语言；
- 删除只为旧 gate 存在的 `SocialBehaviorComponent` 字段。若该组件没有其他用途则整体删除；若 SU7 的选择 adapter 仍需结构化活动数据，应以名称清楚的 `SocialSessionEligibilityComponent` 取代；
- 移除旧 `Packages/SU7Crisis` 世界包，创建 `SU7SocialPropagation`，而非改名后保留旧数据。

基础 runtime 的推荐、屏幕投影、帖子、阅读与互动 effects 继续存在，但按照本文件的资格规则加强。

## 10. 下游世界包

### 10.1 SU7SocialPropagation

该包保存 100 个 agent、事故账号/帖子、关系图和 SU7 专属研究指标。它在 reaction 中声明 `social_behavior_rate` policy，并明确它的活动参数、会话预算、原创发帖权限、卡片层点赞规则和 tick 语义。它不包含微塑料实验 context 或旧冷却逻辑。

验收：全体社交 agent 只经 `SocialSessionRound` 进入平台；浏览—打开—互动可以在同一会话连续发生；每个会话有可审计结束原因。

### 10.2 MicroplasticNarrative

该包复用同一 100-agent 人口结构、人格数值、兴趣权重、关注图和手机绑定，但 `social_seed.json` 必须中性：没有 SU7 事故帖、事故标签、事故账号和事故记忆。它使用 `big_five_extraversion` policy。

实验比较四份唯一不同正文：

| 条件 ID | 风险后果 | 解决方案 |
| --- | --- | --- |
| `high_consequence_low_solution` | 高 | 低 |
| `high_consequence_high_solution` | 高 | 高 |
| `low_consequence_low_solution` | 低 | 低 |
| `low_consequence_high_solution` | 低 | 高 |

作者、标签、基础互动、推荐参数、agent、种子集合、policy、运行长度、provider 和配对随机输入固定。实验帖标签不编码条件。

`social_propagation:DeliverSocialPost` 是唯一直接投放能力：它验证 `post_id`、目标账号/手机、来源和位置；写 `source=experiment_direct` exposure；同步写入目标 `ScreenComponent.feed_items`；并写投放审计。它不改动普通推荐公式。基础互动以 seed 帖子的显式计数初始化，不能伪造为 agent 操作。

完全曝光：T1 向 100 个目标账号投放。冷启动：T1 只向固定、预先分层抽取的种子集合投放；后续非种子只可获得普通推荐来源的自然曝光。微塑料主分析只统计具有 `view_history` 的阅读后互动；卡片点赞可另作描述性指标。

## 11. 验收与实施顺序

基础包的 interface 测试：

1. capability recipes 与 world recipes 按声明组合，同名 ID 拒绝加载；
2. 每 round 每 agent 最多一个会话，预算、结束原因和 trace 正确；
3. 导航可连续发生；终局命令后不再请求该 agent 的下一步决策；
4. 评论/转发不能绕过已打开帖子；同账号不能重复转发同一帖子；
5. 并行 decision 时，effect 与 SQLite 提交严格按稳定 agent 顺序；
6. 不存在 `SocialActivityGateTick`、旧 cooldown、`rumor_*` 或旧 context 的可执行路径。

实施顺序：

1. 扩展 Package capability data composition，并测试冲突与 identity；
2. 创建 `SocialPropagationBase`，实现两个 selection adapter、会话 effect、通用 recipes、SQLite 约束和导出契约；
3. 删除旧 SU7 调度路径，创建 `SU7SocialPropagation` 并完成 focused smoke；
4. 创建中性 seed 的 `MicroplasticNarrative`、直接投放和两种实验配置；
5. 加入四条件配对运行、checkpoint 与统计导出。

开始实现前须由研究方确认：SU7 的结构化活动参数及 tick 含义；SU7 是否允许原创发帖；点赞是否允许卡片层；微塑料的四份文本、基础互动、种子规模、`alpha/beta_e`、会话预算、总 round 与 provider 配置。
