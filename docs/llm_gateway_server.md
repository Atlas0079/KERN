# Gemma server gateway

`tools/llm_gateway_console.sh` starts one `llama-server` replica per GPU in
`GPUS` and a loopback-only aggregator on port 8080. The aggregator routes
non-streaming OpenAI-compatible requests to the healthy replica with the fewest
in-flight requests. It rejects streaming requests.

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
    "api_key": "local"
  }
}
```

Bind workflow roles to `local_gateway` and explicitly set each model name. The
gateway is an external runtime service; it does not alter KERN world
transactions.
