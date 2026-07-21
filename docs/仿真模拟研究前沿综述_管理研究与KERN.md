# 仿真模拟研究前沿综述：管理研究与 KERN 的切入点

> 更新：2026-07-18
> 读者：管理学合作者、KERN 场景研究者
> 用途：选题、文献综述、研究设计。本文不是对真实组织或人群行为的预测声明。

## 结论先行

对管理研究而言，仿真最有价值的用途是研究“若干明确机制共同作用时，组织或市场
会产生什么后果”，尤其适合现实中难以随机试验、成本高或有风险的问题，例如危机
沟通、平台治理、供应链扰动、创新扩散和员工协作。

目前可把相关研究分为三层。基于规则的 agent-based model（ABM）仍是机制解释、
稳健性分析和政策比较的主方法；数字孪生适合把运营流程模型与持续数据连接起来；
LLM agent simulation 正快速扩展自然语言互动和异质决策的表达力，但其外部效度仍须
逐项检验。论文写作中最稳妥的定位是：**用仿真实验比较机制和干预方案，不声称模型
自动预测现实社会。**

KERN 当前最合适的研究定位是“可审计的机制实验平台”：世界状态、规则、effect、
事件日志和 checkpoint 由可复现内核控制；LLM 只处于受约束的决策层。这样的结构比
让 LLM 直接改写世界状态更适合管理研究中的机制追踪、复现实验和敏感性分析。

## 仓库已有材料

仓库已在 [paper_research/README.md](paper_research/README.md) 中索引了 Generative
Agents、OASIS、AgentSociety、LLM 模拟人类样本、信任行为和谣言传播等论文原文或
arXiv 页面。它们集中于 LLM 社会仿真。此前没有一份把这些工作同管理研究中的 ABM、
数字孪生、验证和研究设计连接起来的文献综述，本文补足这一空白。

## 一张方法地图

| 方法 | 核心问题 | 主要证据来源 | 最适合的管理问题 | 主要风险 |
| --- | --- | --- | --- | --- |
| 机制型 ABM | 个体规则和互动如何产生宏观结果？ | 理论、访谈、行为数据、制度规则 | 组织学习、扩散、竞争、危机响应 | 规则任意设定、只展示单次结果 |
| 离散事件/流程仿真 | 资源和流程瓶颈如何影响绩效？ | 流程数据、作业时间、容量数据 | 排队、服务运营、供应链、产能 | 忽略行为反馈和适应性 |
| 数字孪生 | 如何将运营模型与实时或历史数据连接？ | 传感器、ERP、物流和生产数据 | 韧性、预测性维护、排程、情景演练 | 把“有数据看板”误称为数字孪生 |
| LLM agent simulation | 在结构化约束下，语言互动和异质解释会怎样演化？ | prompt、角色数据、任务行为评测 | 舆情、沟通、协商、服务互动 | 幻觉、提示词敏感、群体代表性不足 |

管理论文需要先说明研究问题属于哪一列，再匹配建模和验证方案。把四类方法混用会
削弱因果解释：例如用未经校准的 LLM 输出估计真实市场份额，结论通常站不住；用
LLM 丰富危机信息的解释与转发机制，再比较不同干预规则，则是可检验的研究设计。

## 必读文献：方法基础与管理研究

| 文献 | 贡献 | 对管理研究的直接启发 |
| --- | --- | --- |
| Davis, Eisenhardt & Bingham (2007), *Developing Theory Through Simulation Methods*, **Academy of Management Review** | 将仿真定位为理论建构工具：从简单、可追踪的假设出发，观察机制组合的后果。 | 先写清微观行为规则与宏观理论命题，再做情景实验；仿真输出用来发展和反驳理论，而非替代实证。 |
| Fioretti (2013), *Agent-Based Simulation Models in Organization Science*, **Organizational Research Methods** | 系统说明组织研究中 agent、规则、互动和涌现结果的关系。 | 适合作为组织行为、组织学习与组织设计类论文的方法论入口。 |
| Rand & Rust (2011), *Agent-based modeling in marketing: Guidelines for rigor*, **International Journal of Research in Marketing** | 为管理领域 ABM 提出严谨性要求，包括模型说明、校准、验证和稳健性。 | 可直接转化为论文的方法与附录清单。 |
| Grimm et al. (2020), *The ODD Protocol…A Second Update*, **Journal of Artificial Societies and Social Simulation** | ODD 是描述仿真模型的标准模板：Overview、Design concepts、Details。 | 用 ODD 写模型，审稿人才能复核实体、状态变量、过程、随机性和初始化。 |
| Grazzini, Richiardi & Tsionas (2017), *Bayesian estimation of agent-based models*, **Journal of Economic Dynamics and Control** | 说明 ABM 可以被估计和比较，不必只做演示性运行。 | 有真实行为或运营数据时，应将参数校准和不确定性纳入研究设计。 |

## 必读文献：数字孪生与运营管理

数字孪生的关键不是三维可视化，而是“某个具体物理或业务系统的模型、数据连接和
持续更新”。管理研究中，它特别适合运营韧性、库存与产能配置、物流网络和服务流程。

| 文献 | 贡献 | 可落地的研究问题 |
| --- | --- | --- |
| Ivanov & Dolgui (2021), *A digital supply chain twin for managing the disruption risks and resilience in the era of Industry 4.0*, **Production Planning & Control** | 提出供应链孪生用于扰动风险与韧性管理。 | 某种信息延迟、备货策略或供应中断规则如何影响恢复速度和成本？ |
| Fuller et al. (2020), *Digital Twin: Enabling Technologies, Challenges and Open Research*, **IEEE Access** | 梳理数字孪生所需的数据、模型、连接和治理问题。 | 研究设计应说明数据如何更新模型、模型输出如何影响决策、更新频率为何合理。 |

对 KERN 而言，当前更接近“可审计的情景仿真平台”，还不应直接称为完整数字孪生。
当某个业务场景具备持续数据接入、校准和回写决策闭环后，才适合使用数字孪生表述。

## 必读文献：LLM agent 与社会/组织仿真

这一方向在 2023 年后增长很快。它的真实贡献是让 agent 可以处理自然语言、记忆、
角色和开放式互动；它尚未证明能自然代表任意真实人群。研究者应把 LLM 视为需要
单独评测的行为模块。

| 文献 | 当前证据 | 使用时的边界 |
| --- | --- | --- |
| Park et al. (2023), *Generative Agents: Interactive Simulacra of Human Behavior*, **UIST** | 展示记忆、反思和计划架构可支持可交互的多 agent 社会环境。 | 证明架构可行；不等于证明生成角色代表真实组织成员。 |
| Aher, Arriaga & Kalai (2023), *Using Large Language Models to Simulate Multiple Humans and Replicate Human Subject Studies*, **ICML** | 在若干已有的人类实验任务上比较 LLM 角色模拟与原实验结果。 | 应逐任务验证，不能从少数实验外推到所有管理行为。 |
| Argyle et al. (2023), *Out of One, Many: Using Language Models to Simulate Human Samples*, **PNAS** | 探索用语言模型生成“硅样本”以近似部分群体态度分布。 | 可作为补充性假设生成或实验设计工具；涉及代表性时必须与真实样本对照。 |
| Horton (2023), *Large Language Models as Simulated Economic Agents: What Can We Learn from Homo Silicus?*, **NBER Working Paper 31122** | 讨论 LLM 作为经济行为主体的潜力与识别问题。 | 适合用来界定“模拟主体”与“真实人的因果证据”之间的距离。 |
| OASIS (2024, preprint) 与 AgentSociety (2025, preprint) | 探索大规模 LLM 社会仿真、平台机制和计算基础设施。 | 可参考工程设计和实验规模；预印本结论应标明同行评审状态。 |

## 管理研究中应如何验证

验证分为四件不同的事，缺一不可。

1. **实现验证**：模型是否按设计执行？KERN 的 effect transaction、事件日志、
   checkpoint 和测试主要覆盖这一层。
2. **结构验证**：规则、实体、资源约束和信息路径是否符合案例事实或理论？需要领域
   专家、制度材料、流程文档或访谈支持。
3. **行为验证**：个体或局部互动是否与观察数据相符？例如阅读率、转发率、反应时间、
   服务处理时间或库存补货规则。
4. **结果验证**：模型能否复现多个未参与校准的宏观模式？例如峰值时间、扩散曲线、
   结构差异或干预排序。

一个可靠的管理仿真研究至少报告：参数来源与范围、初始化、随机种子、运行次数、
敏感性分析、失败运行处理、用于校准的数据和留出的验证数据。仅展示一条“很像真实
世界”的运行轨迹不构成验证。

## 可直接采用的研究设计

以 KERN 的 SU7Crisis 危机沟通方向为例，可形成如下可发表的机制问题：

> 在信息不完整的技术型危机中，官方澄清的发布时间、触达路径与平台推荐机制如何
> 共同影响错误信息的持续时间和纠正覆盖？这一关系是否受到用户异质性与社交网络
> 结构的调节？

对应设计：

1. 用公开事件时间线、平台公开内容和已有文献定义信息节点、角色类别和干预规则。
2. 将可观测的阅读、互动、澄清和响应时间用于校准；不把 LLM 生成的对话当作现实
   观测数据。
3. 将 LLM 限制在“看到信息后如何解释、是否发言、如何表达”的决策层；世界写入仍经
   recipe/effect 和事务规则执行。
4. 对照基线、早澄清、定向触达、降低错误信息曝光等情景，每个情景重复多次运行。
5. 报告错误信息曝光、澄清覆盖、平均响应时延、极端扩散概率等事先定义的结果。
6. 用参数扫描检验结论是否依赖某一组 prompt、模型版本、网络结构或行为参数。

这样形成的是“干预机制的情景实验”证据。若要声称某项政策在现实中一定有效，还需
要真实世界的准实验、现场实验或更强的外部验证。

## 给合作写作者的阅读顺序

第一周先读 Davis et al.、Rand & Rust、Grimm et al.，建立管理仿真的理论、严谨性和
报告框架。第二周根据题目选择 Ivanov & Dolgui（运营/供应链）或 Park、Aher、Argyle
（LLM 与社会互动）。随后再回到 KERN 的具体场景和日志，设计一个能被数据校准和
反驳的机制问题。

论文中建议使用以下表述：

> 本研究构建可审计的多主体情景仿真，用于比较既定行为机制与管理干预的条件性后果；
> 模型不以单次运行预测具体真实个体或事件为目标。

## 参考文献与原始来源

1. Davis, J. P., Eisenhardt, K. M., & Bingham, C. B. (2007). Developing theory through simulation methods. *Academy of Management Review, 32*(2), 480–499. https://doi.org/10.5465/amr.2007.24351453
2. Fioretti, G. (2013). Agent-based simulation models in organization science. *Organizational Research Methods, 16*(2), 227–242. https://doi.org/10.1177/1094428112470006
3. Rand, W., & Rust, R. T. (2011). Agent-based modeling in marketing: Guidelines for rigor. *International Journal of Research in Marketing, 28*(3), 181–193. https://doi.org/10.1016/j.ijresmar.2011.04.002
4. Grimm, V., et al. (2020). The ODD Protocol for describing agent-based and other simulation models: A second update to improve clarity, replication, and structural realism. *Journal of Artificial Societies and Social Simulation, 23*(2), 7. https://doi.org/10.18564/jasss.4259
5. Grazzini, J., Richiardi, M., & Tsionas, M. (2017). Bayesian estimation of agent-based models. *Journal of Economic Dynamics and Control, 77*, 26–47. https://doi.org/10.1016/j.jedc.2017.01.004
6. Ivanov, D., & Dolgui, A. (2021). A digital supply chain twin for managing the disruption risks and resilience in the era of Industry 4.0. *Production Planning & Control, 32*(9), 775–788. https://doi.org/10.1080/09537287.2020.1768450
7. Fuller, A., Fan, Z., Day, C., & Barlow, C. (2020). Digital Twin: Enabling technologies, challenges and open research. *IEEE Access, 8*, 108952–108971. https://doi.org/10.1109/ACCESS.2020.2998358
8. Park, J. S., et al. (2023). Generative agents: Interactive simulacra of human behavior. *Proceedings of UIST 2023*. https://doi.org/10.1145/3586183.3606763
9. Aher, G. V., Arriaga, R. I., & Kalai, A. T. (2023). Using large language models to simulate multiple humans and replicate human subject studies. *Proceedings of ICML 2023*. https://arxiv.org/abs/2208.10264
10. Argyle, L. P., et al. (2023). Out of one, many: Using language models to simulate human samples. *Proceedings of the National Academy of Sciences, 120*(46). https://arxiv.org/abs/2209.06899
11. Horton, J. J. (2023). Large language models as simulated economic agents: What can we learn from Homo Silicus? *NBER Working Paper 31122*. https://doi.org/10.3386/w31122
12. Gao, C., et al. (2024). OASIS: Open agent social interaction simulations with one million agents. *arXiv preprint*. https://arxiv.org/abs/2411.11581
13. Wang, Z., et al. (2025). AgentSociety: Large-scale simulation of LLM-driven generative agents advances understanding of human behaviors and society. *arXiv preprint*. https://arxiv.org/abs/2502.08691

预印本文献可用于说明研究前沿和技术路线；正式理论或实证结论优先引用同行评审论文，
并在论文中标注预印本状态。
