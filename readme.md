# KERN 仿真沙盒内核

KERN（Knowledge, Environment, Runtime, Narrative）是一个基于实体-组件系统（ECS）与数据驱动的离散事件仿真（DES）沙盒内核。本项目专为多智能体与大语言模型（LLM）实验设计，致力于提供一个**可配置、可复用、可审计**的底层运行基座。

在传统的智能体实验中，场景结构、交互逻辑与状态更新往往被深度耦合。KERN 通过将“世界定义”、“规则匹配”、“状态结算”和“智能体接入”彻底分离，使得研究者可以通过纯配置的方式快速切换场景与规则，而无需修改核心代码。

## 核心特性

- **数据驱动的世界构建**：摒弃复杂的类继承，采用 ECS 架构。场景中的实体及其能力（如生命值、背包、位置）均通过纯数据组件组合定义，极大地提升了环境的可扩展性。
- **声明式规则与统一结算**：将智能体的主动交互与环境的被动事件抽象为声明式规则。KERN `WorldState` 的状态写入被收束为统一的“变更指令”，交由底层执行器集中落地；外部 runtime 具有独立的一致性边界。运行档案支持状态演化审计和 checkpoint 恢复。
- **语义与物理的安全隔离**：为外部智能体提供标准的感知与动作接口。智能体输出的决策指令必须经过系统规则引擎的合法性校验后，才能转化为底层的物理状态变更。这一机制有效拦截了 LLM 常见的“动作幻觉”，防止错误决策污染底层世界状态。

## 验证场景

内核当前保留一个可运行的世界包：

- **野营（Camping）**：当前 no-LLM smoke 场景，覆盖长期任务、容器、采集与营火等基础链路。
CompanionRobot 与 SpaceWerewolf 的场景设计只保留为文档资产，不再保留可运行数据。

## 快速开始与文档

- 🚀 **[开发者快速上手](docs/开发者快速上手.md)**：包含环境配置、运行命令与结果产出说明，帮助您在 5 分钟内跑通第一个模拟场景。
- ⚙️ **[配置详解](docs/配置详解.md)**：详细说明系统运行时的各项参数、场景切换方式以及 LLM 接入配置。

## 许可证

This repository is licensed under `GNU GPL v3.0`. See [LICENSE](LICENSE).

In addition, redistributed or publicly published modified versions must preserve attribution to the original project name, author, and project URL in a user-visible project document. See [NOTICE](NOTICE).
