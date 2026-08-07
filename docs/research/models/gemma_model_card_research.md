# Gemma model card and Transformer inference research

## Identity: `Gemma4-32b-it` is not an official Google Gemma model ID

Google's official Gemma documentation lists the Gemma 3 sizes as 1B, 4B, 12B,
and 27B. The matching official Hugging Face instruction-tuned large checkpoint
is [`google/gemma-3-27b-it`](https://huggingface.co/google/gemma-3-27b-it), not
`Gemma4-32b-it` or `gemma-4-31B-it`.

The local API script's default folder/model name is `gemma-4-31B-it`, but a
folder name does not establish model identity. Its use of
`AutoModelForMultimodalLM`, `processor.parse_response`, and
`enable_thinking` also cannot be treated as evidence that the checkpoint is
Gemma 3. Before choosing an implementation or interpreting its speed, inspect
the deployed folder's `config.json` and record at least `model_type`,
`architectures`, `torch_dtype`, and any `quantization_config`. Compare those
values with the official model card/configuration for the actual checkpoint.

Primary sources:

- [Google: Gemma documentation](https://ai.google.dev/gemma/docs)
- [Google's Gemma 3 27B instruction model card on Hugging Face](https://huggingface.co/google/gemma-3-27b-it)
- [Transformers Gemma 3 model documentation](https://huggingface.co/docs/transformers/main/en/model_doc/gemma3)

## What the official Gemma 3 path supports

The official model card provides a Transformers loading example based on
`Gemma3ForConditionalGeneration` and `AutoProcessor`; use the exact
Transformers version stated by that model card (or a newer version whose
release notes retain Gemma 3 support). Do not infer compatibility from a
generic `AutoModelForMultimodalLM` load succeeding. The model documentation is
the versioned API reference for the Gemma 3 classes and inputs.

Transformers' attention backend is selected with the
`attn_implementation` loading argument. Its official performance guide
documents PyTorch SDPA and FlashAttention 2; the Gemma 3 model documentation
states the attention implementations available to that architecture. A
supported FlashAttention 2 installation can materially improve decode/prefill
throughput, but it is a separate CUDA extension with its own CUDA/PyTorch/
driver compatibility requirements. On a server whose NVIDIA driver cannot run
the required CUDA runtime, select a supported PyTorch SDPA/eager path rather
than forcing that extension.

Primary sources:

- [Transformers: attention backend selection](https://huggingface.co/docs/transformers/main/en/perf_infer_gpu_one#flashattention-2)
- [Transformers: SDPA](https://huggingface.co/docs/transformers/main/en/perf_infer_gpu_one#scaled-dot-product-attention-sdpa)
- [Transformers Gemma 3 API reference](https://huggingface.co/docs/transformers/main/en/model_doc/gemma3)

## Two A100s: capacity and throughput are different

`device_map="auto"` is Hugging Face's Big Model Inference placement mechanism.
It spreads layers across devices so a model fits, but it is not tensor-parallel
generation: one request still executes its layers in sequence. It can solve
memory pressure without making a single generated token twice as fast, and the
current script's process-wide `threading.Lock` additionally allows only one
request to generate at a time.

For a verified architecture supported by Transformers distributed inference,
use its documented tensor-parallel path (for example the documented
`tp_plan="auto"` launch pattern) to use both GPUs for one request. That is a
different mechanism from `device_map="auto"`. If the real checkpoint is not a
supported Gemma 3 checkpoint, consult the architecture owner's model card and
Transformers support table before changing it.

For experimental throughput where independent requests are acceptable, two
separate replicas (one GPU each) can increase aggregate requests per second;
they do not reduce the latency of one request. Measure both prompt tokens/s and
generated tokens/s at the experiment's actual prompt and `max_new_tokens`
sizes before making a serving decision.

Primary sources:

- [Accelerate: Big Model Inference and `device_map`](https://huggingface.co/docs/accelerate/main/en/concept_guides/big_model_inference)
- [Transformers: distributed inference / tensor parallelism](https://huggingface.co/docs/transformers/main/en/perf_infer_gpu_multi)
- [Transformers: tensor-parallel support list](https://huggingface.co/docs/transformers/main/en/perf_infer_gpu_multi#supported-models)

## Immediate conclusion

The reported slow speed is plausibly caused by the serving topology rather
than the raw A100 capability: the script uses `device_map="auto"`, serializes
all calls with one lock, and uses standard `generate` rather than a continuous
batching server. Confirming the checkpoint from its configuration is the first
required measurement; until then, it is unsafe to apply Gemma 3-specific
versions, attention options, or tensor-parallel settings.
