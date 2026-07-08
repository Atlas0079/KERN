# 谣言传播社交平台场景落地计划

本文记录“在 KERN 中模拟社交平台谣言传播，并测试干预方案”的当前共识。它不是稳定架构说明，而是用于后续开发和上下文压缩后的快速恢复。

## 目标

最终目标是构建一个新的社交传播实验场景：

- 模拟谣言在社交平台上的曝光、打开、评论、转发、发帖和澄清触达。
- 测试不同干预方案对谣言传播的影响，例如无干预、官方澄清、专家评论、平台标注、降权或限流。
- 提供一个独立可视化模块，读取 KERN checkpoint/archive 和 social SQLite runtime 数据，展示传播曲线、互动漏斗、关键账号/帖子和干预效果。

这个场景不要求 KERN 维持完整具身智能体验。KERN 在这里主要作为 tick loop、agent workflow、memory、effect、event log、checkpoint 和外部 runtime 扩展能力的实验编排器。地点、移动、物品和长期任务可以退化到最低限度。

## 已有基础

当前代码已经具备以下可复用部分：

- `SQLiteSocialPlatformRuntime`：位于 `KERN/external_runtimes/social_platform.py`，维护账号、兴趣、帖子、标签、关注、曝光、浏览历史、点赞、评论、转发、checkpoint。
- social effects：位于 `KERN/executor/_effect_social_platform.py`，包括 `ObserveSocialFeed`、`ObserveSocialPost`、`CreateSocialPost`、`InteractSocialPost`、`FollowSocialAccount`。
- `ScreenComponent`：位于 `KERN/models/components/screen.py`，作为 agent 手机屏幕的短期可操作上下文。
- planner/grounder 屏幕隔离：`observer.build_agent_perception(...)` 只在 grounder 模式、手机在 inventory、屏幕上下文新鲜时暴露 raw `post_id`。
- social profile sampler：位于 `KERN/external_runtimes/social_profile_seed.py`，已经能生成身份背景、媒体习惯、社交风格、兴趣、大五人格和 LLM 背景 prompt。
- runtime provider 路由：`AgentControlComponent.provider_id` 已经能让特定 agent 使用 `runtime.action_providers[provider_id]`。

当前 `Data/SocialPhone/` 是 smoke 场景，只用于验证手机和 social effects，不应直接扩展成最终谣言传播场景。

## 关键设计判断

### 不给每个社交操作强行加任务

不建议把刷帖、打开、点赞、评论、转发、发帖都做成 1 tick task。

原因：

- 社交平台微动作本来是低成本瞬时动作，任务化会污染 task 生命周期。
- 不同性格/身份的操作频率会被错误建模成任务创建频率。
- LLM prompt 会被迫围绕“接任务/完成任务”组织，和社交平台使用体验不符。
- 传播指标会混入大量无意义 task 事件。

### 新场景使用自己的基础 reactions

默认 `Data/Reactions.json` 中有：

```text
AdvanceTick -> AgentControlTick(max_actions_in_tick=50)
```

同时 `NoActiveTaskRule` 对没有任务的 agent 会持续触发。这对具身任务场景可接受，但对瞬时社交动作会导致同一 tick 内反复决策。

谣言传播场景应新增自己的基础 reaction 文件，例如：

```text
Data/RumorSpread/Reactions.json
```

该文件不启用默认 `advance_tick_agent_control`。它应只保留必要的 tick 维护，并通过新的 social activity gate 控制 agent 何时获得一次社交行动机会。

### 操作频率只决定何时行动，不决定做什么

身份背景、职业、媒体习惯、外向性、神经质等只用于决定 agent 是否在某个 tick 获得社交平台行动机会。

具体行为由 LLM 根据上下文判断：

- 刷推荐
- 打开帖子
- 评论
- 转发
- 发原创反应帖
- 关注账号
- 暂不行动

也就是说，频率模型不能直接写死“外向的人一定评论”或“学生一定转发”。它最多可以让 agent 更频繁获得“表达机会”或“浏览机会”，最终动作仍由 LLM 基于上下文决定。

## 新场景建议结构

建议新增：

```text
Data/RumorSpread/World.json
Data/RumorSpread/Entities/rumor_agents.json
Data/RumorSpread/Recipes.json
Data/RumorSpread/Reactions.json
Data/RumorSpread/social_seed.json
runtime_config.rumor_spread.smoke.json
```

第一版可以把所有 agent 放在一个虚拟地点，例如 `rumor_lab_room`。每个 agent 持有一部 phone，phone 的 `ScreenComponent.runtime_id` 指向同一个 social runtime，`account_id` 对应平台账号。

## SocialBehaviorComponent

已新增正式组件 `SocialBehaviorComponent`：

```text
KERN/models/components/social_behavior.py
```

它已接入 component exports、`Entity` component union、`data.builder` 构建路径和通用 checkpoint dataclass 序列化路径。

职责：只描述社交平台使用频率和触发敏感度，不描述具体动作选择。

当前字段：

```python
base_activity_rate: float
active_hours: list[int]
cooldown_ticks: int
last_social_opportunity_tick: int
event_reaction_sensitivity: float
expression_opportunity_rate: float
routine_browse_rate: float
fatigue: float
```

含义：

- `base_activity_rate`：每 tick 获得社交行动机会的基础概率。
- `active_hours`：高活跃时段，用 KERN game time 或 tick 映射。
- `cooldown_ticks`：两次社交行动机会之间的最低间隔。
- `last_social_opportunity_tick`：上次获得机会的 tick，用于冷却。
- `event_reaction_sensitivity`：近期显著事件提高行动机会概率的强度。
- `expression_opportunity_rate`：更容易出现“想表达/回应”的机会，但仍不决定动作。
- `routine_browse_rate`：日常刷帖机会权重。
- `fatigue`：连续多次行动后的抑制项，避免少数 agent 过密行动。

身份背景到频率参数的映射可以来自 `social_profile_seed`：

- 学生、无固定工作、自由职业、重度媒体用户：更高 `base_activity_rate`，更短 `cooldown_ticks`。
- 稳定上班族：午休、晚间活跃更高，工作时段低。
- `quiet_low_media`：低频率、长冷却。
- `online_first`、短视频重度用户：高频率、短冷却。
- 神经质较高或事件敏感度高：遇到高显著事件时更容易获得反应机会。
- 外向性较高：可提高表达机会概率，但不直接规定评论/转发/发帖。

## SocialActivityGateTick effect 设计

这是下一步开发的核心 effect。用户需要在实现后详细审查它的实际逻辑和规则。

### 目的

`SocialActivityGateTick` 在每个 world tick 中扫描社交传播场景的 agent，决定哪些 agent 本 tick 获得一次 LLM 社交行动机会。

它解决两个问题：

- 替代默认 `NoActiveTask -> AgentControlTick(max_actions=50)` 控制流，避免瞬时动作在同一 tick 内循环。
- 把身份背景、媒体习惯、事件显著性等因素用于“何时行动”，同时保留 LLM 决定“做什么”。

### 触发方式

在 `Data/RumorSpread/Reactions.json` 中由 `WorldTickAdvanced` 触发：

```json
{
  "id": "rumor_world_tick_social_activity_gate",
  "on_event": "WorldTickAdvanced",
  "bundle": {
    "effects": [
      {
        "effect": "SocialActivityGateTick"
      }
    ]
  }
}
```

该场景不应同时启用默认 `advance_tick_agent_control`。

### 当前实现位置

当前实现文件：

```text
KERN/executor/_effect_social_activity.py
```

effect 已注册到：

```text
KERN/effect_contract.py
```

workflow 单次机会 helper 位于：

```text
KERN/agent_workflow/runtime.py
```

当前新增 helper：

```python
run_social_activity_cycle(...)
```

它复用 `run_workflow_cycle(...)` 的 memory patch、decision contract、command 编译和 operation 执行路径，但通过 `max_commands` 限制一次机会最多执行指定数量的命令。默认 `max_actions=1`。

### 输入参数

第一版 effect 可以支持：

```json
{
  "effect": "SocialActivityGateTick",
  "agent_query": {
    "type": "has_component",
    "target": "candidate",
    "component": "AgentControlComponent"
  },
  "provider_id": "social_llm",
  "max_agents_per_tick": 10,
  "max_actions_per_agent": 1,
  "default_screen_context_window_ticks": 2
}
```

可简化为无参数 effect，默认扫描所有带 `AgentControlComponent` 和 `SocialBehaviorComponent` 的 agent。

当前 binder 已实现的字段：

```text
provider_id
max_agents_per_tick
max_actions_per_agent
default_screen_context_window_ticks
base_rate_multiplier
```

默认值：

```text
provider_id = ""
max_agents_per_tick = 999999
max_actions_per_agent = 1
default_screen_context_window_ticks = 2
base_rate_multiplier = 1.0
```

### 候选 agent 过滤

一个 agent 必须满足：

- 存在 `AgentControlComponent` 且 `enabled=true`。
- 存在 `DecisionArbiterComponent` 或至少能进入 workflow cycle。
- 存在 `SocialBehaviorComponent`，或有可解析的默认社交频率配置。
- inventory 中有带 `ScreenComponent` 的 phone，且该 phone 有 `runtime_id/account_id`。
- 如果指定 `provider_id`，agent 的 `AgentControlComponent.provider_id` 应匹配，或 gate 使用指定 provider 显式调用。

第一版可以不做严格设备/session 安全校验，延续当前 social runtime 设计。

当前实现扫描所有带 `SocialBehaviorComponent` 的 entity，并要求：

- `AgentControlComponent.enabled=true`。
- inventory 里存在带 `ScreenComponent` 的 phone。
- phone screen 有非空 `runtime_id/account_id`。
- 能找到 workflow provider：优先 effect 参数 `provider_id`，否则使用 agent 的 `AgentControlComponent.provider_id`，再否则使用 default provider。

### 概率计算

每个候选 agent 计算一次机会分数：

```text
opportunity_probability =
  base_activity_rate
  * active_hour_multiplier
  * cooldown_multiplier
  * fatigue_multiplier
  + salient_event_bonus
  + recent_social_memory_bonus
```

建议规则：

- 冷却期内概率为 0，除非有特别高显著事件。
- 非活跃时段降低概率，但不一定为 0。
- 连续多 tick 行动后提高 fatigue，降低后续概率。
- 最近看到或记住与谣言相关的高显著内容时，提高反应机会概率。
- 概率上限应 clamp 到 `0.0..1.0`。

当前第一版公式较保守，尚未接入显著事件 bonus：

```text
probability =
  clamp01(base_activity_rate)
  * base_rate_multiplier
  * active_hour_multiplier
  * (1 - fatigue)
```

当前规则：

- `cooldown_ticks` 内直接跳过。
- 如果 `active_hours` 为空，`active_hour_multiplier = 1.0`。
- 如果 `active_hours` 非空，当前小时命中则为 `1.0`，否则为 `0.35`。
- 当前小时读取 `ws.game_time.hour`；如果不存在，则用 `tick % 24`。
- 每次获得机会后 `fatigue += 0.1` 并 clamp 到 `0.0..1.0`。
- `SocialBehaviorComponent.per_tick(...)` 会让 fatigue 每 tick 下降 `0.05`，但是否被调用取决于现有 per-tick 机制是否覆盖该组件。

随机性必须可复现，建议使用：

```text
run_id | tick | agent_id | gate_id
```

派生稳定随机数，避免同一实验配置重复运行时结果漂移。

当前实现使用：

```text
run_id | tick | agent_id | SocialActivityGateTick
```

其中 `run_id` 来自 `ws._checkpoint_run_id` 或 `ws.services["run_id"]`，缺失时为空字符串。

### 机会类型

gate 可以生成一个轻量机会类型，放入 `mode_context`，但它不能直接指定具体动作。

建议值：

- `routine_browse`：日常刷平台机会。
- `event_reaction`：近期事件或记忆触发的反应机会。
- `expression_opportunity`：表达欲/参与讨论机会。
- `followup_check`：对近期打开或互动过的话题做后续查看。

这些值用于给 LLM 提供心理/情境提示，不应被 grounder 当作固定动作。

当前实现只在 `routine_browse` 和 `expression_opportunity` 之间选择：

- 如果 `expression_opportunity_rate >= routine_browse_rate`，机会类型为 `expression_opportunity`。
- 否则为 `routine_browse`。

这仍然只影响 `mode_context` 提示，不直接决定动作。

### 调用 workflow

`SocialActivityGateTick` 不应调用 `run_agent_control_tick(...)` 的 while loop，因为该函数会依赖 interrupt rule 并可能多次行动。

更合适的实现是新增一个专用 helper，例如：

```python
run_social_activity_cycle(
    ws,
    actor_id,
    workflow,
    reason,
    mode_context,
    max_actions=1,
)
```

它可以复用 `run_workflow_cycle(...)` 的 memory patch、planner/grounder 和 command 编译逻辑，但每次机会最多执行一个 command。

如果不想新增大 helper，第一版也可以在 effect handler 中直接调用 `run_workflow_cycle(...)`，然后只应用第一条 operation；但这需要谨慎处理 workflow outcome，避免绕过现有错误记录。

当前实现采用新增 helper 的方案：

- `SocialActivityGateTick` 调用 `run_social_activity_cycle(...)`。
- `run_social_activity_cycle(...)` 设置 `social_activity_opportunity=true`、`grounder=true`、`max_social_actions`。
- 它调用 `run_workflow_cycle(..., max_commands=max_actions)`。
- 如果 workflow 返回多个 commands，只保留前 `max_actions` 个，默认只执行第一个。
- 它使用现有 `_apply_operations(...)` 执行 operation，所以 interaction log 和 executor error 行为仍沿用原有 workflow。

注意：为了让 gate 的 mode context 不被 LLM provider 内部覆盖，`LLMActionProvider` 的 decision mode context 已做轻量调整，会保留传入的 social activity 字段。

### mode_context

传给 LLM 的 `mode_context` 应包含：

```json
{
  "social_activity_opportunity": true,
  "activity_reason": "routine_browse",
  "opportunity_type": "routine_browse",
  "max_social_actions": 1,
  "grounder_screen_context_window_ticks": 2,
  "salient_context": [],
  "rumor_experiment": {
    "enabled": true,
    "active_rumor_ids": []
  }
}
```

`salient_context` 是自然语言或结构化摘要，用于解释为什么此刻有社交行动机会。它可以来自：

- 最近 social event memory。
- 新谣言 seed。
- 关注账号发布或转发。
- 官方澄清。
- 线下事件。
- 平台热度变化。

当前实现先传入空 `salient_context`，尚未接入谣言/澄清/线下事件显著性。

### 输出事件

建议 effect 返回 gate 事件，便于面板和调试：

```json
{
  "type": "SocialActivityGateEvaluated",
  "tick": 10,
  "candidate_count": 30,
  "selected_count": 4,
  "selected_agent_ids": ["agent_001", "agent_007"],
  "skipped": {
    "cooldown": 12,
    "missing_phone": 0,
    "probability": 14
  }
}
```

对每个被选中的 agent 可选返回：

```json
{
  "type": "SocialActivityOpportunityGranted",
  "entity_id": "agent_001",
  "account_id": "acc_001",
  "opportunity_type": "event_reaction",
  "probability": 0.42,
  "roll": 0.18,
  "tick": 10
}
```

注意：这些 gate 事件只说明“机会发放”，不说明 agent 最终做了什么。最终动作仍由 social effects 和 interaction log 记录。

当前实现会返回：

- 每个入选 agent 一个 `SocialActivityOpportunityGranted`。
- 最后一个 `SocialActivityGateEvaluated` 汇总事件。

`SocialActivityOpportunityGranted` 当前包含：

```text
entity_id
phone_id
account_id
opportunity_type
probability
roll
tick
outcome
```

`SocialActivityGateEvaluated.skipped` 当前统计：

```text
cooldown
missing_phone
provider
probability
disabled
```

### 状态更新

当 agent 获得机会时：

- 更新 `SocialBehaviorComponent.last_social_opportunity_tick`。
- 可增加短期 `fatigue`。
- 如果 workflow 最终 noop，也仍然算一次机会；这符合现实中的“打开手机但没有行动”或“犹豫后不参与”。

当 agent 因冷却、缺设备或 provider 缺失被跳过时，不更新机会 tick。

当前实现中，如果 workflow 最终 noop 或失败，只要机会已发放，仍会更新 `last_social_opportunity_tick` 并增加 fatigue。

### 错误处理

如果单个 agent 的 workflow 报错，不应中断整个 gate tick。应记录错误并继续处理其他 agent。

只有以下情况应返回 `ExecutorError`：

- effect 参数非法。
- 必需 runtime service 缺失。
- provider 配置整体不可用，且没有任何 agent 能被处理。

当前实现只有 `ws.services.execute` 缺失会返回 `ExecutorError`。单个 agent 缺 phone/provider/冷却/概率未命中都进入 skipped 汇总，不中断 gate。

### 与 LLM prompt 的关系

planner 应看到：

- agent 身份背景。
- 最近记忆。
- 当前社交机会原因。
- 谣言/澄清/平台热度的语义摘要。
- 可用动作的 planner hint。

planner 不应看到 raw `post_id`。

grounder 可以在屏幕上下文新鲜时看到：

- feed slot。
- `post_id`。
- `current_post.post_id`。
- phone `entity_id`。

这沿用当前 `ScreenComponent` 的 planner/grounder 隔离设计。

## 反应类发帖

`CreateSocialPost` 本身不应该凭空发生。它只是一个可执行动作。让 LLM 有理由发帖，需要给它上下文来源。

建议新增以下事件或信息源：

- `RumorSeedEvent`：谣言种子出现。
- `ClarificationEvent`：官方或专家澄清出现。
- `OfflineSituationEvent`：线下事实或生活事件，例如学校通知、通勤异常、社区传闻。
- `SocialSalienceEvent`：某个话题在平台上显著升温。
- social memory：agent 最近看到、打开、评论、转发过的相关内容。

这些事件进入 event log 和 memory policy 后，`SocialActivityGateTick` 可以提高相关 agent 的行动机会，并在 `mode_context.salient_context` 中解释触发原因。

LLM 再决定是否：

- 发原创观点。
- 评论当前帖子。
- 转发并附言。
- 继续观察。
- 忽略。

## 干预方案

第一版建议实现三组实验：

- baseline：无干预。
- clarification：官方账号或专家账号发布澄清帖。
- downrank_or_label：平台对谣言帖打标或降权。

后续可扩展：

- 专家评论置顶。
- 限制转发。
- 限制推荐。
- 对高风险账号降权。
- 反向推荐澄清内容。

干预最好成为 social runtime 的正式 operation，并通过 KERN effect 暴露，例如：

```text
ApplySocialIntervention
```

第一版如果为了快速验证，也可以由实验脚本直接调用 social runtime，但最终为了证明 KERN 扩展性，建议进入 effect contract。

## 可视化模块

可视化面板可以独立于 KERN runtime 实现。它应读取：

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

可视化不需要作为 agent UI。它是研究者观察面板。

## PHEME 数据接入约定

当前决定优先使用 PHEME 作为真实社交平台文本来源，而不是让 LLM 凭先验生成“真实谣言”。

PHEME 在本项目中的职责是提供外部实验输入：

- source tweet 文本。
- rumor / non-rumor 标签。
- 事件目录名，例如 `charlie-hebdo`、`ferguson` 等。
- source tweet 的发布时间，用于映射到 KERN tick。
- source tweet 作者信息可选保留；默认不把 PHEME 作者映射到 KERN agent。

PHEME 不负责提供完整 KERN agent：

- 不要求 PHEME 提供完整 follow graph。
- 不要求 PHEME 提供 `account_interests`。
- 不要求 PHEME 提供 KERN agent 身份背景。
- 不要求把 PHEME 作者和已有 agent 做身份匹配。
- 不要求第一版完整导入 reaction tree。

这些缺失信息由 KERN 场景生成器补齐：

- 100 个模拟用户仍由 `social_profile_seed` 或后续场景生成脚本产生。
- 用户兴趣写入 `account_interests`，用于当前推荐算法的 tag 匹配。
- follow graph 由场景生成器基于兴趣、核心账号和少量随机边构造。
- PHEME 帖子通过 tags 与用户兴趣和研究统计关联。

当前新增离线转换脚本：

```powershell
.\.venv\Scripts\python.exe tools\convert_pheme_to_social_seed.py <PHEME解压目录> `
  --rumor-count 1 `
  --noise-count 100 `
  --output Data/RumorSpread/social_seed.pheme.generated.json
```

脚本识别常见 PHEME 目录形态：

```text
<event>/rumours/<thread>/source-tweets/*.json
<event>/non-rumours/<thread>/source-tweets/*.json
```

输出格式兼容现有 `seed_social_platform_runtime_from_file(...)`：

- `accounts`：默认使用 `external_pheme_rumor_source` 和 `external_pheme_background_source` 等外部来源账号；这些账号不是 KERN agent。
- `posts`：source tweets 转成 social runtime posts。
- `follows`：暂为空，后续由 100-agent 场景生成器合并。
- `metadata`：记录来源、采样 seed、数量和转换说明；当前 seed loader 会忽略它。

转换后的帖子 tags 约定：

```text
pheme
<event>
rumor | non_rumor
source_post
background   # 仅 non_rumor/noise 帖子
```

注意：当前第一版只导入 PHEME source tweets。PHEME reactions 可以后续作为预置评论、预置转发或评估对照，但今晚优先让 KERN LLM agents 在运行中产生互动数据。

如果后续确实需要保留 PHEME 原始作者作为平台账号，转换脚本提供：

```powershell
--source-accounts tweet_authors
```

但默认仍使用外部来源账号，避免把真实数据源作者错误解释成 KERN agent。

## 当前推荐算法

当前 social runtime 的 feed 推荐不是复杂机器学习模型，而是轻量可解释排序。`ObserveSocialFeed` 会对当前 tick 已发布的 active posts 打分，取前 N 个展示，并记录 `exposures`。

公式位置：

```text
KERN/external_runtimes/social_platform.py
```

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
- `engagement` 来自帖子 like/comment/repost 计数。
- `author_affinity` 来自该账号历史 action traces。
- `exploration_noise` 是基于 run/account/post/tick/cursor 的稳定随机探索。
- `seen_penalty` 来自该账号历史 exposures。

已修复一个重要时间问题：feed candidate 现在只包含 `created_tick <= current_tick` 的帖子。否则 scheduled clarification 或后续 PHEME 噪声帖会提前出现在 feed 中。

## Workflow View Profile

社交传播场景不能直接沿用具身智能场景的完整物理感知。若 100 个 agent 位于同一地点，当前感知链路会把同地点实体放入 `visible_entities`，并且 memory policy 可能把同地点事件/interaction 写入记忆，造成上下文和记忆污染。

当前已新增 workflow view profile 机制：

```text
KERN/agent_workflow/view_profile.py
```

runtime config 支持：

```json
{
  "env": {
    "WORKFLOW_VIEW_PROFILE": "social_platform"
  }
}
```

也支持后续用 JSON 文件覆盖：

```json
{
  "env": {
    "WORKFLOW_VIEW_PROFILE_JSON": "Data/RumorSpread/workflow_view_profile.json"
  }
}
```

内置 profile：

- `embodied_default`：默认具身场景行为，保留 visible entities、map topology、reachable locations、同地点事件和 interaction 记忆。
- `social_platform`：社交传播场景行为，关闭物理实体、地图、可达地点、同地点记忆污染，保留 agent 身份、记忆、inventory phone 和 grounder 的 phone screen context。
- `social_platform_debug`：调试用，关闭地图/可达地点和同地点记忆，但保留 visible entities。

`runtime_config.rumor_spread.smoke.json` 当前已启用：

```text
WORKFLOW_VIEW_PROFILE=social_platform
```

这不是单纯 prompt 层过滤。profile 会被注入 workflow view：

- `observer.build_agent_perception(...)` 根据 profile 裁剪 LLM 可见信息。
- `memory_policy.build_memory_patch(...)` 根据 profile 过滤同地点无关事件和他人 social feed 事件。
- 默认 profile 保持旧场景兼容。

对 100-agent 谣言传播生成场景的建议：

- 仍优先使用隔离 room 或少量分组 room，作为物理层双保险。
- 即使未来放在同一地点，`social_platform` profile 也会避免大部分 prompt 膨胀和记忆污染。
- KERN agent 之间的传播关系应主要来自 social runtime，而不是物理同地点观察。

## 推荐第一版验收标准

第一版开发完成后，应至少证明：

1. 新 `RumorSpread` 场景不启用默认 `AgentControlTick(max_actions=50)` 控制流。
2. `SocialActivityGateTick` 每 tick 最多给每个入选 agent 一次 LLM 社交行动机会。
3. 身份背景/媒体习惯只影响行动机会概率，不直接决定具体社交动作。
4. LLM 可以基于屏幕、记忆和显著上下文选择刷帖、打开、评论、转发、发帖或 noop。
5. social runtime 中能统计谣言相关曝光、打开、评论、转发和澄清触达。
6. 针对 baseline 和至少一种干预方案能导出可视化所需数据。

当前已完成 1 到 4 的基础控制流部分：

- 新增 `Data/RumorSpread/Reactions.json`，不包含默认 `advance_tick_agent_control`。
- 新增 `SocialActivityGateTick`，每个入选 agent 默认最多执行一个 command。
- 新增 `SocialBehaviorComponent`，当前只控制行动机会概率/冷却/疲劳。
- 新增 `Data/RumorSpread/` 最小场景和 `runtime_config.rumor_spread.smoke.json`。

尚未完成 5 到 6：

- social runtime 还没有正式 `rumors` / `interventions` 表。
- dashboard 和指标导出尚未实现。
- 显著事件 bonus、澄清触达和干预策略仍是下一阶段。

## 下一步实现建议

建议按以下顺序开发：

1. 新增 `SocialBehaviorComponent` 和序列化/构建支持。
2. 新增 `SocialActivityGateTick` effect contract、binder、handler。
3. 新增 `run_social_activity_cycle(...)` 或等价单动作 workflow helper。
4. 新建 `Data/RumorSpread/` 最小场景和 `runtime_config.rumor_spread.smoke.json`。
5. 扩展 social runtime 的 rumor/intervention 数据模型。
6. 增加针对 gate、场景、social runtime 指标的测试。
7. 再做独立 dashboard。

实现 `SocialActivityGateTick` 后，需要把实际逻辑、概率公式、跳过原因、事件输出和测试结果补充回本文档，供用户详细审查。

当前验证命令：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_social_activity_gate tests.test_social_platform_runtime tests.test_social_platform_effects tests.test_social_phone_config_runtime
.\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
.\.venv\Scripts\python.exe -m compileall KERN tests default_orchestrator.py
.\.venv\Scripts\python.exe -m unittest tests.test_executor_transactions tests.test_agent_workflow_runtime tests.test_archive
```

当前验证结果均通过。
