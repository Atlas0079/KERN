# Google Gemma 4 31B IT：模型卡核查与 Transformers 部署说明

核查日期：2026-07-30。此前将该模型识别为 Gemma 3 27B 是错误的；本文件以 Google 在 Hugging Face 发布的 **[`google/gemma-4-31B-it`](https://huggingface.co/google/gemma-4-31B-it)** 模型卡及其仓库配置为准。仓库的 `model_type` 是 `gemma4`，架构类是 `Gemma4ForConditionalGeneration`，并非 Gemma 3。

## 模型身份与能力

`gemma-4-31B-it` 是 Google DeepMind 发布的 Gemma 4 **指令微调、稠密（dense）多模态模型**。它接收文本与图像、生成文本；31B 这一规格不支持音频输入。模型卡给出的总参数为 **30.7B**，其中视觉编码器约 **550M**；上下文窗口为 **256K tokens**，词表为 **262K**。Gemma 4 支持系统消息、函数调用、可配置的 thinking，以及 140+ 语种的预训练覆盖。

来源：[官方模型卡的 Dense Models 表](https://huggingface.co/google/gemma-4-31B-it#dense-models)；[官方模型仓库元数据](https://huggingface.co/api/models/google/gemma-4-31B-it)。

## 已发布架构细节

模型卡说明，Gemma 4 交错使用局部滑动窗口注意力和全局注意力，最终层为全局注意力；全局层使用共享 K/V 与 proportional RoPE，以控制长上下文内存需求。仓库的 [`config.json`](https://huggingface.co/google/gemma-4-31B-it/raw/main/config.json) 给出了该 31B checkpoint 的精确运行时配置：

| 项目 | 值 |
| --- | --- |
| 权重 dtype | `bfloat16` |
| 文本 Transformer 层数 | 60 |
| 隐藏维度 / MLP 中间维度 | 5,376 / 21,504 |
| 注意力头 / KV 头 | 32 / 16 |
| 全局层 KV 头 | 4 |
| 注意力布局 | 每 6 层 1 个 `full_attention`，其余为 `sliding_attention` |
| 局部窗口 | 1,024 tokens |
| 最大位置 | 262,144 tokens |
| RoPE | 全局层 proportional RoPE（theta=1,000,000）；局部层标准 RoPE（theta=10,000） |
| 视觉编码器 | 27 层、hidden size 1,152、16 注意力头、patch size 16 |
| 默认视觉 soft tokens | 每图 280 |

这解释了两个实际部署事实：它是 **31B 稠密模型**，每个新 token 都要经过完整的 60 层；同时，混合注意力降低了长提示词的 KV-cache 代价，却不代表 256K 上下文在单张 80GB 卡上可以无代价使用。

## 对两张 A100 80GB + Transformers 的含义

BF16 下，仅 30.7B 参数的理论权重下界约为 57.2 GiB（`30.7e9 × 2 bytes`）。Google 的 [Gemma 4 总览](https://ai.google.dev/gemma/docs/core) 给出 31B BF16 静态加载约 **69.9GB**（含 20% loading overhead）的估算，并明确该值不含上下文/KV cache 和 supporting software；实际加载仍须以服务器实测为准。因此：

- 对常见的短提示词实验，一张 A100 80GB 通常是合理的单实例目标；是否确实装得下应以启动后的 `torch.cuda.max_memory_allocated()` 和 `nvidia-smi` 为准。
- 256K 是模型支持的最大上下文。服务默认不再人为设定输出 token 上限；未传 `max_tokens` 时，它会把输入 prompt 之外的全部剩余上下文作为生成上限。上下文越长，prefill 时间和 KV cache 越大，实际是否能达到 256K 仍取决于单卡显存。
- `device_map="auto"` 会按设备内存把模块放到可见 GPU。它解决装载问题，不能把一个请求的逐 token 解码变成两张卡的线性加速；跨卡的层间通信可能增加延迟。这个结论来自 Transformers 的设备映射语义和自回归生成方式，需用本机基准验证。
- 当前 [`tools/gemma4_openai_api.py`](../tools/gemma4_openai_api.py) 有一个覆盖整个 `generate()` 的互斥锁，因此单个进程一次只处理一个请求。若每张卡能够完整放下一份模型，优先指定 `--device cuda:0` 和 `--device cuda:1` 启动两个独立进程并在客户端分流；这提升实验**并发吞吐**，不缩短同一条请求的解码时间。

## 双单卡副本启动

`tools/gemma4_openai_api.py` 的 `--device` 参数将整个 checkpoint 放在一张指定 GPU，不再使用 `device_map="auto"` 跨卡切分。先在 GPU 0 启动第一个实例，确认显存余量后再启动 GPU 1 的第二个实例；两个实例必须使用不同端口：

```bash
python3 tools/gemma4_openai_api.py --device cuda:0 --port 8081
python3 tools/gemma4_openai_api.py --device cuda:1 --port 8082
```

每个实例的 `/health` 会返回其 `device`。客户端应将彼此独立的实验请求分流到这两个端口；同一个对话仍只应发送到其中一个实例。若任一实例因显存不足无法加载，请停止该实例，保留现有的跨卡部署，并根据实测上下文长度调整方案。

## 官方 Transformers 路径与低风险优化

官方 Transformers 文档的 Gemma 4 示例使用 `AutoModelForImageTextToText` / `AutoModelForMultimodalLM`、`AutoProcessor`、`attn_implementation="sdpa"`，并在生成示例中使用 `cache_implementation="static"`。对当前脚本，先做可度量的 A/B 试验：

1. 记录同一批固定 prompt 的输入 token 数、首 token 时间、解码 tokens/s、峰值显存及 GPU 利用率；将短上下文和真实实验上下文分开测。
2. 在当前已安装的 Transformers 版本支持时，测试显式 `attn_implementation="sdpa"`；测试静态缓存时，应按请求的最大上下文和最大生成长度预分配，因此先确认显存余量。两项均是官方示例出现的配置，并非对所有版本、批大小和输入长度的性能保证。
3. 保持 thinking 关闭，除非实验设计需要推理轨迹。模型卡说明 thinking 会生成 thought channel；这会增加实际输出 token，直接拉长一次生成。
4. 图像任务用模型自带的 `AutoProcessor`，并在图像位于同一提示词时将图像放在文本前。Gemma 4 的可选视觉 token 预算为 70、140、280（默认）、560、1120；较小预算可降低视觉 prefill 成本，但会改变视觉精度，须作为实验条件记录。
5. 若量测确认瓶颈是解码而非排队，评估 Google 提供的量化 Gemma 4 QAT checkpoint 与其**匹配的 MTP assistant/draft model**。Google 将这一路径列为 speculative decoding：需要量化的主模型和 drafter，目标是加速 token 生成。当前脚本只加载一个 BF16 主模型、调用普通 `generate()`，没有加载 MTP assistant，因此不具备这项加速。它需要单独验证量化后实验质量和软件兼容性。

来源：[Hugging Face Transformers Gemma 4 文档](https://huggingface.co/docs/transformers/main/en/model_doc/gemma4)（SDPA、static cache、图像处理与 token 预算）；[官方模型卡 Best Practices](https://huggingface.co/google/gemma-4-31B-it#best-practices)（采样、thinking、图像顺序和视觉预算）；[Google Gemma 4 总览](https://ai.google.dev/gemma/docs/core)（显存估算、QAT 与 speculative decoding）。

## 建议的验收基线

在不改变模型、prompt 和采样参数的前提下，分别测量：

| 部署方式 | 回答的问题 |
| --- | --- |
| 现有 `device_map="auto"` 单进程 | 当前端到端延迟和单流 tokens/s |
| 单卡完整模型（若可装载） | 跨 GPU 分层是否在拖慢单请求 |
| 两个单卡实例、两个并发请求 | 是否提高实验总吞吐 |
| SDPA / static cache 的受控 A/B | 当前 PyTorch/Transformers 组合是否实际受益 |

报告应同时保留输入/输出 token 数和是否启用 thinking；只比较请求耗时会把模型实际生成长度和队列等待混入“推理速度”。
