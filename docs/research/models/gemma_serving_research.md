# Gemma serving research

## Model identity must be confirmed first

`gemma-4-31b-it` is not an official Google model ID that this research could
verify. Google's Gemma 3 documentation lists 1B, 4B, 12B, and 27B models; the
published instruction-tuned 27B checkpoint is `google/gemma-3-27b-it`.
The repository also contains conflicting local names: the gateway defaults to
`gemma-4-26B...`, while a probe script defaults to `gemma-4-31b-it`.

Before serving the uploaded folder, inspect its `config.json` and
`tokenizer_config.json`. In particular, confirm `model_type`, `architectures`,
and `quantization_config`. The actual configuration, rather than the folder
name, determines whether vLLM can load it and which quantization flags apply.

Sources:

- [Google Gemma documentation](https://ai.google.dev/gemma/docs)
- [Official Gemma 3 27B instruction model card](https://huggingface.co/google/gemma-3-27b-it)
- [vLLM supported models](https://docs.vllm.ai/en/latest/models/supported_models.html)

## Recommended service boundary

For a vLLM-supported Hugging Face-format checkpoint, run vLLM only on the
school server's loopback interface. Its OpenAI-compatible server then becomes
the sole server-side API boundary:

```bash
vllm serve /absolute/path/to/model-folder \
  --served-model-name school-gemma \
  --host 127.0.0.1 \
  --port 8000 \
  --dtype bfloat16 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
```

Use `--dtype bfloat16` only for a compatible BF16 checkpoint. A quantized
checkpoint must use the vLLM-supported loading path indicated by its confirmed
configuration. Start with an 8K context limit and measure GPU headroom; a
27B BF16 model has roughly 54 GiB of weights before KV cache and runtime
overhead.

Verify the server on the school machine:

```bash
curl http://127.0.0.1:8000/v1/models
```

Official vLLM reference: [OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html).

## VPN-only local API use

While connected to the school VPN, create a local SSH tunnel from the client
machine:

```bash
ssh -N -L 8000:127.0.0.1:8000 user@school-server
```

Ordinary OpenAI-compatible clients can then use
`http://127.0.0.1:8000/v1` as `base_url` and `school-gemma` as the model name.
For example:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="local")
response = client.chat.completions.create(
    model="school-gemma",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message.content)
```

Keep the server bound to `127.0.0.1`; access remains constrained by the VPN
and SSH authentication rather than exposing the model port publicly.
