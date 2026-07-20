#!/usr/bin/env bash
# Manage replicated llama-server workers and a loopback-only aggregation gateway.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODEL="${MODEL:-/mnt/nv1/home/BA24204058/gemma-4-26B-A4B-it-qat-q4_0-gguf/gemma-4-26B_q4_0-it.gguf}"
LLAMA_SERVER="${LLAMA_SERVER:-$HOME/src/llama.cpp/build/bin/llama-server}"
GATEWAY="${GATEWAY:-$SCRIPT_DIR/llm_gateway.py}"
STATE_DIR="${STATE_DIR:-$HOME/.local/state/kern-llm-gateway}"
GPUS="${GPUS:-0,7}"
PARALLEL="${PARALLEL:-2}"
CONTEXT_SIZE="${CONTEXT_SIZE:-8192}"
GATEWAY_PORT="${GATEWAY_PORT:-8080}"
WORKER_PORT_BASE="${WORKER_PORT_BASE:-8081}"

usage() {
	cat <<'EOF'
Usage: llm_gateway_console.sh {start|stop|status|logs|health}

Environment overrides: MODEL, LLAMA_SERVER, GATEWAY, GPUS, PARALLEL,
CONTEXT_SIZE, GATEWAY_PORT, WORKER_PORT_BASE, STATE_DIR.
EOF
}

pid_alive() { [[ -f "$1" ]] && kill -0 "$(<"$1")" 2>/dev/null; }

stop_pid() {
	local pid_file="$1"
	if pid_alive "$pid_file"; then
		kill "$(<"$pid_file")"
		for _ in {1..20}; do pid_alive "$pid_file" || break; sleep 1; done
		pid_alive "$pid_file" && kill -9 "$(<"$pid_file")"
	fi
	rm -f "$pid_file"
}

start() {
	[[ -x "$LLAMA_SERVER" ]] || { echo "llama-server not executable: $LLAMA_SERVER" >&2; exit 1; }
	[[ -f "$MODEL" ]] || { echo "model not found: $MODEL" >&2; exit 1; }
	[[ -f "$GATEWAY" ]] || { echo "gateway not found: $GATEWAY" >&2; exit 1; }
	mkdir -p "$STATE_DIR"
	IFS=',' read -r -a gpu_list <<< "$GPUS"
	local workers=() gpu port index=0
	for gpu in "${gpu_list[@]}"; do
		gpu="${gpu//[[:space:]]/}"
		port=$((WORKER_PORT_BASE + index))
		workers+=("http://127.0.0.1:$port")
		if pid_alive "$STATE_DIR/worker-$gpu.pid"; then
			echo "GPU $gpu worker already running"
		else
			CUDA_VISIBLE_DEVICES="$gpu" nohup "$LLAMA_SERVER" --model "$MODEL" --jinja --gpu-layers 999 --ctx-size "$CONTEXT_SIZE" --parallel "$PARALLEL" --host 127.0.0.1 --port "$port" >"$STATE_DIR/worker-$gpu.log" 2>&1 &
			echo $! >"$STATE_DIR/worker-$gpu.pid"
			echo "started GPU $gpu worker on port $port"
		fi
		index=$((index + 1))
	done
	local workers_csv; workers_csv=$(IFS=,; echo "${workers[*]}")
	if ! pid_alive "$STATE_DIR/gateway.pid"; then
		nohup python3 "$GATEWAY" --workers "$workers_csv" --host 127.0.0.1 --port "$GATEWAY_PORT" >"$STATE_DIR/gateway.log" 2>&1 &
		echo $! >"$STATE_DIR/gateway.pid"
		echo "started gateway on port $GATEWAY_PORT"
	fi
}

stop() {
	stop_pid "$STATE_DIR/gateway.pid"
	for pid_file in "$STATE_DIR"/worker-*.pid; do [[ -e "$pid_file" ]] && stop_pid "$pid_file"; done
}

status() {
	for pid_file in "$STATE_DIR"/*.pid; do
		[[ -e "$pid_file" ]] || { echo "no managed processes"; return; }
		if pid_alive "$pid_file"; then echo "running: $(basename "$pid_file" .pid) pid $(<"$pid_file")"; else echo "stopped: $(basename "$pid_file" .pid)"; fi
	done
	nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader
}

logs() { tail -n "${LINES:-100}" "$STATE_DIR"/*.log; }
health() { python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:${GATEWAY_PORT}/health', timeout=5).read().decode())"; }

case "${1:-}" in
	start) start ;;
	stop) stop ;;
	status) status ;;
	logs) logs ;;
	health) health ;;
	*) usage; exit 2 ;;
esac
