# MetaSim 危机管理 PPT 页面设计稿 2026-07-09

项目展示名：

```text
MetaSim: An Extensible LLM-based Generative Agent Simulation Platform and Applications in Crisis Management
```

标题页由单张图片承载，交给 Banana2 / GPT Image 2 处理。正文页、页脚和文档内项目名统一使用 `MetaSim`。

## 页面清单

### 1. 标题页

主要目的：展示项目名、会议主题和视觉基调。

实际内容：

- 标题：`MetaSim`
- 副标题：`An Extensible LLM-based Generative Agent Simulation Platform and Applications in Crisis Management`
- 作者、单位、会议信息、日期。

素材：

- 使用 `slides/title.png` 或后续 Banana2 生成的新封面图。
- tex 中该页仍为整页图片，不在 LaTeX 内排标题文字。

### 2. 定位

主要目的：说明 MetaSim 是可扩展的多智能体仿真内核。

实际内容：

- 页标题：`定位`
- 主标签：`Meta Simulator`
- 正文：
  - `MetaSim 是一个基于 ECS（Entity-Component System）与数据驱动的离散事件仿真沙盒内核。提供世界建模、规则运行、状态结算、智能体接入和过程记录等基础能力。`
  - `开发者可以把不同主题的场景快速放入同一个运行框架中，例如野营、生存、狼人杀、竞技场、陪伴机器人或教学环境。`

素材：

- 当前使用 `slides/定位.png`。

### 3. 问题

主要目的：说明多主题 LLM agent 实验的工程成本问题。

实际内容：

- 页标题：`问题`
- 主标签：`场景工程`
- 正文：
  - `需要评估 LLM Agent 的研究者，通常要把同一个智能体放进不同主题的环境中观察行为，例如生存、协作、博弈、教学或社会互动。`
  - `但每换一个主题，往往都要重新实现世界结构、行动规则、状态更新、任务流程、日志记录和 Agent 接口。实验关注点还没进入行为分析，工程成本已经先出现。`

素材：

- 当前使用 `slides/问题.png`。

### 4. 能力

主要目的：展示 MetaSim 的六个基础能力。

实际内容：

- 页标题：`能力`
- 六个能力块：
  - `定义世界`：地点、路径、角色、物品、设施
  - `定义规则`：动作、任务、条件、事件响应
  - `运行演化`：Tick 推进、状态变化、持续任务
  - `接入 Agent`：感知输入、动作输出、规则校验
  - `记录过程`：事件日志、交互日志、checkpoint
  - `复用场景`：同一内核承载不同主题
- 页底说明：
  - `MetaSim 具有以上能力，然而生成的模拟环境仍以离散空间与离散时间为基础，适合表达地点、事件和任务驱动的世界演化。`

素材：

- 当前用 TikZ 六宫格，不需要外部图片。

### 5. 优点

主要目的：总结 MetaSim 对多场景仿真的直接收益。

实际内容：

- 页标题：`优点`
- 五个内容块：
  - `快速建模`：场景内容通过数据组合表达，主题切换更加轻量。
  - `主题无关`：同一套基座可以承载生存、博弈、陪伴、教学等场景。
  - `过程可审计`：状态变化、事件链和 Agent 交互都有记录入口。
  - `适配 LLM 实验`：感知、动作、校验和反馈形成稳定边界，便于替换不同 Agent 策略。
  - `支持复现实验`：Checkpoint 与日志让研究者回到关键时刻分析行为原因。

素材：

- 当前用 LaTeX columns 排版，不需要外部图片。

### 6. 流程

主要目的：展示 MetaSim 的运行闭环。

实际内容：

- 页标题：`流程`
- 页面主体为流程图。

素材：

- 当前使用 `slides/流程.png`。
- 后续可替换为新版流程图，保留同样干净风格。

### 7. 边界

主要目的：展示 MetaSim 如何防止 LLM action hallucination，并说明世界状态更新边界。

实际内容：

- 页标题：`边界`
- 图上方文字：
  - `MetaSim 系统在大语言模型代理尝试不存在的动作时，防止动作幻觉，并引导其重新规划。`
- 页面主体为边界图。
- 图下方文字：
  - `世界状态保持不变。只有经过验证的配方/效果才能修改世界。`

素材：

- 当前使用 `slides/边界.png`。

### 8. 迁移

主要目的：展示 MetaSim 如何从具身智能场景扩展到社交平台风险传播场景。

实际内容：

- 页标题：`迁移`
- 页面上方主句：
  - `MetaSim 易于扩展的特性，使它适合模拟社交平台中风险内容的传播机制。`
- 页面副句：
  - `我们设计了一个独立的社交平台 runtime，并将其接入 MetaSim，使 agent 可以像使用手机一样浏览、打开、评论、转发和发布内容。`
- 页面中部为 agent-phone-platform 互动图：
  - 左侧：多个异质 agent
  - 中间：手机屏幕 / 推荐流
  - 右侧：社交平台 runtime
  - 底部：MetaSim event log / replay / metrics
- 页面底部收束句：
  - `社交平台不只是数据源，而是 agent 可感知、可行动、可复盘的外部环境。`

图中元素：

```text
Agents
- cautious parent
- active student
- quiet observer
- opinionated commenter

Phone Screen
- feed cards
- visible post
- comments
- selected action

Social Platform Runtime
- accounts
- posts
- recommendation
- exposure history
- interactions

MetaSim Trace
- events
- memories
- checkpoints
- metrics
```

图中关系：

```text
Agents observe phone screens
Agents choose social actions
Phone actions call Social Platform Runtime
Runtime returns feed / post events
MetaSim records events, memories, checkpoints, and metrics
```

版面布局：

```text
顶部 18%：主句 + 副句
中部 66%：agent-phone-platform interaction diagram
底部 16%：MetaSim trace / replay / metrics
```

配色：

- agent：Sage / Mist。
- 手机推荐流：white cards with Moss borders。
- 谣言/风险内容：Clay / warm orange。
- 澄清内容：Sage green。
- MetaSim trace：Moss。
- 背景：白色。

Banana2 / GPT Image 2 prompt：

```text
Create a clean academic presentation diagram on a white background, 16:9 aspect ratio.

The diagram explains how generative agents interact with an external social media platform runtime inside MetaSim.

Use a left-to-right interaction scene:

Left side: four simple abstract agent profile cards labeled "Agents". Each card has one small trait label: "cautious", "active", "quiet", "commenter".

Center: a large smartphone screen labeled "Phone Screen". On the phone, show a vertical social feed with three post cards. One card is highlighted in warm orange and labeled "Rumor". Another card is green and labeled "Clarification". Add small action chips near the phone: "open", "comment", "repost", "post".

Right side: a clean runtime box labeled "Social Platform Runtime". Inside it, show small modules: "accounts", "posts", "recommendation", "exposures", "interactions".

Bottom: a thin MetaSim trace layer labeled "MetaSim Event Log / Memory / Checkpoint / Metrics".

Draw arrows from agents to the phone, from phone to Social Platform Runtime, from the runtime back to the phone, and from the runtime down to the MetaSim trace layer.

Style: minimal academic vector infographic with slight hand-drawn warmth, white background, thin lines, clean spacing, muted green and blue-gray palette, warm orange only for risk content. No 3D. No cartoon mascots. No social media logos. No realistic people. Keep labels large and readable.
```

LaTeX 落地：

```tex
\begin{frame}{迁移}
  \small
  MetaSim 易于扩展的特性，使它适合模拟社交平台中风险内容的传播机制。我们设计了一个独立的社交平台 runtime，并将其接入 MetaSim。

  \vspace{0.25cm}
  \centering
  \includegraphics[width=0.92\linewidth,height=4.5cm,keepaspectratio]{slides/metasim_migration.png}

  \vspace{0.15cm}
  {\color{Sage}\footnotesize 社交平台不只是数据源，而是 agent 可感知、可行动、可复盘的外部环境。}
\end{frame}
```

### 9. 社交平台

主要目的：说明社交平台 runtime 在 MetaSim 中承担什么角色。

实际内容：

- 页标题：`社交平台`
- 页面主句：
  - `在社交平台场景中，agent 不直接访问平台数据库，而是通过手机屏幕看到推荐流和帖子，并通过结构化动作产生浏览、互动和发帖行为。`
- 左侧列“平台状态”：
  - 账号
  - 帖子
  - 关注关系
  - 推荐流
  - 曝光记录
- 右侧列“agent 动作”：
  - 浏览推荐流
  - 打开帖子
  - 点赞 / 评论 / 转发
  - 发布帖子
  - 接收澄清
- 底部一句：
  - `平台行为同时写入 event log 和 SQLite social runtime，支持后续复盘与指标导出。`

素材：

- 当前使用 `slides/迁移.png`。
- 图像风格与 `slides/边界.png` 接近：黑白手绘流程图、粗线条、白板感、少量灰色阴影。
- 图像内容已经覆盖：异质 agents、手机推荐流、谣言/澄清帖、社交平台 runtime、exposure/interactions、MetaSim event log / memory / checkpoint / metrics。

### 10. 风险传播

主要目的：具体介绍 RumorSpread 场景。

实际内容：

- 页标题：`风险传播`
- 场景设定：
  - 一个校园/社区相关风险传闻在平台出现。
  - agent 拥有不同媒体使用习惯和风险态度。
  - 推荐流决定谁先看到、看到几次。
  - agent 可浏览、打开、点赞、评论、转发或发帖。
  - 官方澄清在后续 tick 出现。
- 时间线：
  - `tick 0`：背景信息
  - `tick 1`：谣言种子帖
  - `tick 2`：个体互动和扩散
  - `tick 3`：官方澄清
  - `tick 4+`：后续反应

素材：

- 时间线图。
- 谣言节点使用 warm orange。
- 澄清节点使用 green / Sage。

### 11. 输出

主要目的：说明仿真后能观察和导出哪些内容。

实际内容：

- 页标题：`输出`
- 三栏内容：
  - 平台层：曝光次数、打开次数、点赞 / 评论 / 转发、澄清触达
  - agent 层：谁看到、谁质疑、谁转发、谁沉默、为什么行动
  - 机制层：放大节点、敏感人群、响应延迟、干预路径

素材：

- 三栏指标卡。
- 后续可替换为真实 smoke run 的小表格或折线图。

### 12. 价值

主要目的：呈现危机管理中的非传统仿真价值。

实际内容：

- 页标题：`价值`
- 2x2 矩阵：
  - `反事实危机样本`：同一危机可重跑不同响应策略。
  - `机制发现`：观察谣言为何被特定人群放大。
  - `组织盲点暴露`：定位信息延迟、责任链断点、澄清触达不足。
  - `预案压力测试`：在噪声、延迟、异质人群下测试预案弹性。

素材：

- 2x2 矩阵图。
- 可用 LaTeX/TikZ 直接画，避免图片中文字不稳定。

### 13. 进展

主要目的：区分当前已完成内容和下一步。

实际内容：

- 页标题：`进展`
- 左列：已完成
  - MetaSim 核心 tick / reaction / effect / workflow 架构
  - checkpoint / event log / interaction log
  - 社交平台 SQLite runtime
  - 推荐流、曝光、打开、互动、发帖
  - RumorSpread 5-agent 场景
  - generated 100-agent smoke 数据
- 右列：下一步
  - 正式 intervention effect
  - 谣言 / 干预数据模型
  - 指标导出和对比工具
  - 更多危机场景模板
  - 可视化复盘界面

素材：

- 两列清单。
- 不需要外部图片。

## 今日任务

- [x] 保留旧版 Beamer 主题。
- [x] 将正文项目名从 KERN 更新为 MetaSim。
- [x] 删除 Smallville / Concordia 对比页。
- [x] 补回边界页上下说明文字。
- [x] 制作第 8 页迁移图。
- [x] 将迁移页加入 `slides/kern_meta_simulator.tex`。
- [ ] 设计第 9 页社交平台页。
- [ ] 设计第 10 页风险传播页。
- [ ] 准备可展示的社交平台运行摘要。
