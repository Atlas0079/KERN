# 相关论文资料

这个文件夹用于存放 KERN 后续科研写作中可能用到的论文原文或 arXiv 页面。当前优先保存 arXiv HTML 版本；如果 arXiv 暂无 HTML 转换版，则优先保存解压后的 arXiv LaTeX 文本源码；如果没有可用源码，再保存 PDF。

## 文件清单

| 主题 | 论文 | arXiv | 本地文件 | 保存状态 |
| --- | --- | --- | --- | --- |
| 大规模社交模拟参照系统 | OASIS: Open Agent Social Interaction Simulations with One Million Agents | https://arxiv.org/abs/2411.11581 | `2411.11581_oasis.html` | HTML 正文 |
| LLM agent 可信人类行为 | Generative Agents: Interactive Simulacra of Human Behavior | https://arxiv.org/abs/2304.03442 | `2304.03442_generative_agents/` | LaTeX 文本源码 |
| LLM 模拟人类实验参与者 | Using Large Language Models to Simulate Multiple Humans and Replicate Human Subject Studies | https://arxiv.org/abs/2208.10264 | `2208.10264_simulate_multiple_humans.html` | HTML 正文 |
| 硅样本 / 群体态度模拟 | Out of One, Many: Using Language Models to Simulate Human Samples | https://arxiv.org/abs/2209.06899 | `2209.06899_out_of_one_many/` | LaTeX 文本源码 |
| 信任行为模拟 | Can Large Language Model Agents Simulate Human Trust Behavior? | https://arxiv.org/abs/2402.04559 | `2402.04559_llm_agents_trust_behavior/` | LaTeX 文本源码 |
| LLM 社会仿真综述 | From Individual to Society: A Survey on Social Simulation Driven by Large Language Model-based Agents | https://arxiv.org/abs/2412.03563 | `2412.03563_llm_social_simulation_survey.html` | HTML 正文 |
| 大规模 LLM 社会仿真 | AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents Advances Understanding of Human Behaviors and Society | https://arxiv.org/abs/2502.08691 | `2502.08691_agentsociety.html` | HTML 正文 |
| 谣言传播模拟 | Simulating Rumor Spreading in Social Networks using LLM Agents | https://arxiv.org/abs/2502.01450 | `2502.01450_rumor_spreading_llm_agents.html` | HTML 正文 |
| 新闻失真 / 假新闻演化 | The Stepwise Deception: Simulating the Evolution from True News to Fake News with LLM Agents | https://arxiv.org/abs/2410.19064 | `2410.19064_stepwise_deception.html` | HTML 正文 |
| 教育元宇宙综述 | Metaverse in Education: Vision, Opportunities, and Challenges | https://arxiv.org/abs/2211.14951 | `2211.14951_metaverse_in_education/` | LaTeX 文本源码 |
| AI 与元宇宙融合综述 | Artificial Intelligence for the Metaverse: A Survey | https://arxiv.org/abs/2202.10336 | `2202.10336_ai_for_metaverse_survey/` | LaTeX 文本源码 |

## 和 KERN 的关系

- `OASIS`、`AgentSociety` 和 LLM 社会仿真综述可用于说明：大规模 LLM agent 社交模拟已经形成独立研究方向，KERN 可以参考其批量决策和社交平台建模思路。
- `Generative Agents`、`Using LLMs to Simulate Multiple Humans`、`Out of One, Many` 和信任行为论文可用于支撑：LLM 在特定实验任务中可以近似或复现某些人类行为特征。
- 谣言传播和新闻失真论文可用于支撑：LLM agent 已被用于信息传播、谣言扩散和虚假信息演化等接近风险传播的场景。
- 教育元宇宙和 AI-元宇宙综述可用于支撑：虚拟环境适合进行高风险、高成本或现实中难以复现的训练与实验。

## 后续建议

后续如果继续扩展这个资料夹，建议每篇论文都补充一个简短笔记，包含：

1. 这篇论文支持 KERN 论证中的哪一环。
2. 它的实验对象、模拟对象和评估方法是什么。
3. 它不能支持什么，避免过度引用。
