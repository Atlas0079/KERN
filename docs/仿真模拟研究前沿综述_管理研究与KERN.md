# 仿真模拟研究前沿：管理研究视角与 KERN 的定位

> 更新至：2026-07-18。面向管理学合作者的入门综述，不是系统性文献计量综述。
>
> 阅读规则：正文把同行评审论文与预印本分开标注。预印本适合了解技术前沿，不能当作已经确证的管理学证据。

## 一句话结论

当前前沿不是用大语言模型（LLM）替代仿真模型，而是构建**混合仿真**：用数据、规则和约束定义可检验的环境；用 LLM 表达难以手工枚举的异质决策与文本互动；再用校准、验证、重复运行和审计记录判断结论是否可信。

对管理研究而言，仿真最适合回答“某种微观机制在什么边界条件下会产生何种宏观结果”，例如员工沟通如何影响协作、平台推荐如何改变扩散、供应中断如何影响韧性。它不能仅凭一次运行或自然语言输出，就证明真实世界存在某个因果效应或给出可靠预测。

## 1. 先分清四种方法

| 方法 | 核心问题 | 管理研究中的典型用途 | 证据边界 |
| --- | --- | --- | --- |
| 离散事件仿真（DES） | 流程、资源和排队如何随时间演化？ | 服务运营、产能、仓储、排班 | 适合流程约束明确的问题；行为异质性通常较弱。 |
| 基于主体的建模（ABM） | 异质主体在局部规则下互动，会涌现什么结果？ | 组织学习、市场扩散、员工网络、竞争动态 | 机制探索强；规则和参数需要经验依据或敏感性分析。 |
| 数字孪生 | 模型是否与真实业务/物理系统的数据持续连接，并支持决策？ | 供应链、设备维护、运营韧性 | 只有离线模型时应称“仿真”或“数字模型”，不能泛称数字孪生。 |
| LLM 主体仿真 | 能否用语言模型生成异质行动、对话和解释？ | 服务互动、舆情、消费者叙事、情境预实验 | “表达自然”不等于“对真实人群有效”；需单独验证。 |

这四类方法可以组合。比如供应链模型可用 DES 处理产能和交期，用 ABM 表示供应商策略，用实时订单数据构成数字孪生，再以 LLM 生成受规则约束的沟通或应对方案。

## 2. 管理研究中的成熟基础：ABM 是理论实验室

Davis、Eisenhardt 与 Bingham 将仿真定位为理论构建方法：研究者明确主体、决策规则、互动结构和边界条件，观察机制是否足以产生待解释的宏观模式 [1]。这特别适合现实中难以直接操纵、时间跨度很长或存在反馈回路的问题。

Fioretti 强调，组织研究中的 ABM 价值来自异质主体、局部互动和涌现结果 [2]。Rand 与 Rust 则把这一思路转化为营销研究的严谨性要求：问题、行为规则、数据、验证和敏感性分析必须形成完整链条 [3]。因此，仿真论文的贡献不应只是“模型跑出了有趣曲线”，而应是清楚说明哪条机制导致了曲线，以及改变哪项假设后结论是否消失。

适合优先考虑 ABM 的管理问题包括：

- 组织结构、沟通规则和员工异质性如何共同影响协作与创新；
- 社会网络、口碑与平台机制如何影响采用、信任或风险信息扩散；
- 企业或供应商在扰动下如何调整策略，并由此形成系统性韧性或脆弱性；
- 多项局部管理规则叠加后是否产生预料之外的群体行为。

## 3. 数字孪生：关键不在“可视化”，而在数据连接和决策闭环

Kritzinger 等人区分数字模型、数字影子和数字孪生：前两者分别缺少自动数据流或双向联结；严格的数字孪生强调物理/业务系统与模型之间的双向数据连接 [4]。Fuller 等人进一步指出，数据集成、互操作、安全、实时性和模型更新才是实际难点 [5]。

对运营管理最直接的例子是 Ivanov 与 Dolgui 提出的数字供应链孪生：以供应链状态、扰动和恢复策略为输入，比较替代供应、产能调整与库存策略对韧性的影响 [6]。这里的研究价值来自“真实约束 + 可比较的反事实决策”，不是名称本身。

因此，论文写作时应直接交代系统成熟度：

```text
离线、情景化反事实模型 → 仿真 / 数字模型
单向自动导入业务数据     → 数字影子
双向数据连接并参与决策   → 数字孪生
```

## 4. LLM 主体带来的新能力，也带来新的验证负担

Park 等人的 Generative Agents 将记忆、反思和规划结合起来，展示了 LLM 主体在开放文本互动和长期情境连贯性上的能力 [9]。Aher 等人和 Argyle 等人则分别显示：经角色或人口特征提示的语言模型，能够复现部分人类实验模式或群体层面分布 [10][11]。

这些研究带来的新能力很具体：研究者可以较低成本地表达异质主体、自然语言互动、信息解释与情境化决策。但它们没有解除传统 ABM 的验证义务。LLM 的训练资料、模型版本、提示词、采样参数与角色设定都会影响输出；模型可能复现文本中的社会刻板印象，而非真实群体的行为机制。

近期技术工作也同时给出机会和警示。Gao 等人的综述总结了 LLM 参与 ABM 的感知、行动与评估接口 [12，预印本]；AgentSociety 探索了更大规模的 LLM 社会模拟 [13，预印本]。与此同时，Santos、Viana 与 Silva 用真实出行统计检验 LLM 城市模拟，发现叙事上的合理性可以与经验分布显著脱节 [14，预印本]。因此，“看起来像人”最多是可用性线索，不能替代外部有效性检验。

Fachada 等人以 ODD 规范考察 LLM 能否复现 ABM，进一步提示一个很实用的工程原则：应将可执行规格、代码、测试和结果分开验证，而不让 LLM 自由重写世界规则 [15]。

## 5. 一套适合管理论文的研究设计

建议把仿真研究组织为以下链条：

```text
理论问题
→ 可反驳的机制假设
→ 主体、规则、网络和资源约束
→ 与经验数据的映射和校准
→ 基线与反事实实验
→ 留出验证、敏感性和稳健性分析
→ 管理含义与适用边界
```

最低报告标准可采用 ODD 协议：目的、实体/状态/尺度、过程调度、设计概念、初始化、输入数据与子模型都需要被交代 [7]。验证不应只比较一个终点数字；Windrum、Fagiolo 与 Moneta 建议分别检验微观行为、宏观模式与过程轨迹 [8]。

对使用 LLM 的研究，至少再增加四项：

1. 固定并报告精确模型版本、完整提示模板、温度等采样参数和随机种子；
2. 使用多个模型或提示变体做稳健性比较，报告失败和拒绝动作；
3. 将 LLM 输出限制为预先定义的可执行行动空间，而不是让它直接改变仿真状态；
4. 用真实数据的留出样本、已知实验结果或专家编码来检验关键行为与宏观模式。

NIST 的 AI RMF 与其生成式 AI Profile 可作为治理框架：识别风险、测量风险、管理风险，并保留可追溯记录 [16][17]。在管理研究中，这可落实为对模型版本、训练数据风险、隐私、偏差、人工复核和适用边界的明确说明。

## 6. KERN 可以怎样被准确定位

KERN 适合被表述为**受控执行的混合 ABM 基础设施**：

```text
场景数据和规则：定义环境、资源、制度和可行动作
LLM / policy：提出候选行动或自然语言决策
effect binder 与 handler：验证输入并执行允许的状态改变
bundle 事务：失败时回滚，避免世界只改变一半
event log 与 checkpoint：保存行为链路和可重放状态
```

这套结构适合机制探索和可审计反事实比较。例如，可以比较不同澄清策略、推荐规则、库存政策或组织沟通制度在相同初始条件下的结果差异。

它目前不能单独支持以下强主张：

- “模拟结果已经证明真实人群会如此反应”；
- “LLM agent 等同于随机抽取的真实员工、消费者或公众”；
- “一次模拟结果可以直接预测某企业或公共事件的未来”。

要走向经验或预测主张，KERN 场景还需要外部数据校准、留出数据验证、多随机种子、多模型/提示词稳健性分析，以及预先定义的指标和停止条件。

## 7. 给管理学合作者的阅读顺序

先读 [1]、[2]、[3]，理解仿真如何服务理论建构与管理研究严谨性；再读 [6]，理解运营管理中的数字孪生与反事实决策；随后读 [7]、[8]，建立验证和报告标准；最后读 [9]、[10]、[11] 和 [15]，把 LLM 主体视为受检验的新决策层，而不是结论来源。

仓库的 [paper_research/README.md](paper_research/README.md) 已保存多篇 LLM 社会仿真论文的原文或 arXiv 页面，可作为技术阅读材料；本综述补充的是管理研究问题、证据边界和方法规范。

## 参考文献

1. Davis, J. P., Eisenhardt, K. M., & Bingham, C. B. (2007). Developing theory through simulation methods. *Academy of Management Review, 32*(2), 480–499. https://doi.org/10.5465/amr.2007.24351453
2. Fioretti, G. (2012). Agent-based simulation models in organization science. *Organizational Research Methods, 16*(2), 227–242. https://doi.org/10.1177/1094428112470006
3. Rand, W., & Rust, R. T. (2011). Agent-based modeling in marketing: Guidelines for rigor. *International Journal of Research in Marketing, 28*(3), 181–193. https://doi.org/10.1016/j.ijresmar.2011.04.002
4. Kritzinger, W., Karner, M., Traar, G., Henjes, J., & Sihn, W. (2018). Digital Twin in manufacturing: A categorical literature review and classification. *IFAC-PapersOnLine, 51*(11), 1016–1022. https://doi.org/10.1016/j.ifacol.2018.08.474
5. Fuller, A., Fan, Z., Day, C., & Barlow, C. (2020). Digital Twin: Enabling technologies, challenges and open research. *IEEE Access, 8*, 108952–108971. https://doi.org/10.1109/ACCESS.2020.2998358
6. Ivanov, D., & Dolgui, A. (2020). A digital supply chain twin for managing the disruption risks and resilience in the era of Industry 4.0. *Production Planning & Control, 32*(9), 775–788. https://doi.org/10.1080/09537287.2020.1768450
7. Grimm, V., et al. (2020). The ODD Protocol for describing agent-based and other simulation models: A second update to improve clarity, replication, and structural realism. *Journal of Artificial Societies and Social Simulation, 23*(2), 7. https://doi.org/10.18564/jasss.4259
8. Windrum, P., Fagiolo, G., & Moneta, A. (2007). Empirical validation of agent-based models: Alternatives and prospects. *Journal of Artificial Societies and Social Simulation, 10*(1), 8. https://www.jasss.org/10/1/8.html
9. Park, J. S., et al. (2023). Generative Agents: Interactive simulacra of human behavior. *UIST ’23*. https://doi.org/10.1145/3586183.3606763
10. Aher, G. V., Arriaga, R. I., & Kalai, A. T. (2023). Using large language models to simulate multiple humans and replicate human subject studies. *ICML 2023, PMLR 202*. https://proceedings.mlr.press/v202/aher23a.html
11. Argyle, L. P., et al. (2023). Out of one, many: Using language models to simulate human samples. *Political Analysis, 31*(3), 337–351. https://doi.org/10.1017/pan.2023.2
12. Gao, C., et al. (2023). Large language models empowered agent-based modeling and simulation: A survey and perspectives. arXiv:2312.11970. https://arxiv.org/abs/2312.11970 **[预印本]**
13. Piao, J., et al. (2025; v2 2026). AgentSociety: Large-scale simulation of LLM-driven generative agents advances understanding of human behaviors and society. arXiv:2502.08691. https://arxiv.org/abs/2502.08691 **[预印本]**
14. Santos, G. H., Viana, A. C., & Silva, T. H. (2026). When plausible is not realistic: Evaluating human mobility in LLM-based urban simulation. arXiv:2606.13835. https://arxiv.org/abs/2606.13835 **[预印本]**
15. Fachada, N., et al. (2026). Can large language models implement agent-based models? An ODD-based replication study. *Ecological Modelling*. https://doi.org/10.1016/j.ecolmodel.2026.111624
16. Tabassi, E. (2023). *Artificial Intelligence Risk Management Framework (AI RMF 1.0).* NIST AI 100-1. https://doi.org/10.6028/NIST.AI.100-1
17. National Institute of Standards and Technology. (2024). *Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile.* NIST AI 600-1. https://doi.org/10.6028/NIST.AI.600-1
