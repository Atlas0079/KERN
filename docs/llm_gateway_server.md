# Gemma server gateway

`tools/llm_gateway_console.sh` starts one `llama-server` replica per GPU in
`GPUS` and a loopback-only aggregator on port 8080. The aggregator routes each
OpenAI-compatible request to the healthy replica with the fewest in-flight
requests. Streaming SSE responses are relayed without buffering.

## Gemma 4 Transformers service

`tools/gemma4_service_console.sh` manages single-GPU
`gemma4_openai_api.py` replicas and the same loopback-only aggregator. Copy all
three scripts to the server, then run:

```bash
chmod +x gemma4_service_console.sh
./gemma4_service_console.sh start
./gemma4_service_console.sh health
```

The external API is one endpoint at `http://127.0.0.1:8080/v1`; worker ports
start at 8081 and remain internal. By default `GPUS=1,2,3`. Set `GPUS` to a
comma-separated list of available GPU
indices to choose GPUs explicitly. Set `PYTHON` or `GEMMA4_MODEL_PATH` if the
server differs from the defaults. The gateway supports both ordinary and
`stream: true` Chat Completions requests. The default Bearer API key is
`hewei0079`; override it with `GEMMA4_API_KEY` when needed.

## Server installation

Copy `tools/llm_gateway.py` and `tools/llm_gateway_console.sh` to the same
server directory, then make the console executable:

```bash
chmod +x llm_gateway_console.sh
GPUS=0,7 ./llm_gateway_console.sh start
./llm_gateway_console.sh status
./llm_gateway_console.sh health
```

The console uses the model and `llama-server` locations established for the
Gemma 4 server. Override them when necessary:

```bash
MODEL=/path/to/gemma-4-26B_q4_0-it.gguf \
LLAMA_SERVER=/path/to/llama-server \
GATEWAY=/path/to/llm_gateway.py \
GPUS=0,7 \
./llm_gateway_console.sh start
```

Stop only the processes started by this console with:

```bash
./llm_gateway_console.sh stop
```

## Local KERN access

Keep the model service bound to server loopback. While connected to the school
VPN, create a local SSH tunnel:

```powershell
ssh -N -L 8080:127.0.0.1:8080 BA24204058@edison
```

Point an `openai_compat` entry in `llm_providers` at the tunnel:

```json
"llm_providers": {
  "local_gateway": {
    "protocol": "openai_compat",
    "base_url": "http://127.0.0.1:8080",
    "api_prefix": "/v1",
    "api_key": "hewei0079"
  }
}
```

Bind workflow roles to `local_gateway` and explicitly set each model name. The
gateway is an external runtime service; it does not alter KERN world
transactions.
