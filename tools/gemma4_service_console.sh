#!/usr/bin/env bash
# Manage single-GPU Gemma 4 replicas behind one loopback-only API gateway.
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-/mnt/nv1/home/BA24204058/python-envs/gemma4-vllm/bin/python}"
API="${API:-$SCRIPT_DIR/gemma4_openai_api.py}"
GATEWAY="${GATEWAY:-$SCRIPT_DIR/llm_gateway.py}"
STATE_DIR="${STATE_DIR:-$HOME/.local/state/kern-gemma4-service}"
GPUS="${GPUS:-1,2,3}"
REPLICA_COUNT="${REPLICA_COUNT:-2}"
IDLE_GPU_MAX_MEMORY_MIB="${IDLE_GPU_MAX_MEMORY_MIB:-512}"
IDLE_GPU_MAX_UTILIZATION_PERCENT="${IDLE_GPU_MAX_UTILIZATION_PERCENT:-5}"
MODEL_PATH="${GEMMA4_MODEL_PATH:-/mnt/nv1/home/BA24204058/gemma-4-31B-it}"
MODEL_NAME="${GEMMA4_MODEL_NAME:-gemma-4-31B-it}"
API_KEY="${GEMMA4_API_KEY:-hewei0079}"
GATEWAY_PORT="${GATEWAY_PORT:-8080}"
WORKER_PORT_BASE="${WORKER_PORT_BASE:-8081}"
WORKER_READY_TIMEOUT_SECONDS="${WORKER_READY_TIMEOUT_SECONDS:-300}"
GATEWAY_FAILURE_COOLDOWN_SECONDS="${GATEWAY_FAILURE_COOLDOWN_SECONDS:-30}"

usage() {
	cat <<'EOF'
Usage: gemma4_service_console.sh {start|stop|status|logs [gpu]|health}

Environment overrides: PYTHON, API, GATEWAY, STATE_DIR, GPUS, REPLICA_COUNT,
IDLE_GPU_MAX_MEMORY_MIB, IDLE_GPU_MAX_UTILIZATION_PERCENT, GEMMA4_MODEL_PATH,
GEMMA4_MODEL_NAME, GEMMA4_API_KEY, GATEWAY_PORT, WORKER_PORT_BASE,
WORKER_READY_TIMEOUT_SECONDS, GATEWAY_FAILURE_COOLDOWN_SECONDS.
EOF
}

pid_alive() { [[ -f "$1" ]] && kill -0 "$(<"$1")" 2>/dev/null; }

worker_ready() {
	local port="$1"
	"$PYTHON" -c 'import sys, urllib.request; urllib.request.urlopen(f"http://127.0.0.1:{int(sys.argv[1])}/health", timeout=2)' "$port" >/dev/null 2>&1
}

worker_status_line() {
	local gpu="$1" port="$2" pid_file="$STATE_DIR/worker-$gpu.pid"
	if ! pid_alive "$pid_file"; then
		echo "worker gpu=$gpu port=$port state=stopped pid_file=$pid_file log=$STATE_DIR/worker-$gpu.log"
		return 1
	fi
	local pid; pid="$(<"$pid_file")"
	if worker_ready "$port"; then
		echo "worker gpu=$gpu port=$port state=ready pid=$pid"
		return 0
	fi
	echo "worker gpu=$gpu port=$port state=starting-or-unhealthy pid=$pid log=$STATE_DIR/worker-$gpu.log"
	return 1
}

wait_for_workers() {
	local deadline=$((SECONDS + WORKER_READY_TIMEOUT_SECONDS))
	local all_ready=false gpu port pid
	while (( SECONDS < deadline )); do
		all_ready=true
		while IFS=$'\t' read -r gpu port pid; do
			[[ -n "$gpu" ]] || continue
			if ! pid_alive "$STATE_DIR/worker-$gpu.pid"; then
				echo "worker gpu=$gpu exited during startup; see $STATE_DIR/worker-$gpu.log" >&2
				tail -n 40 "$STATE_DIR/worker-$gpu.log" >&2 || true
				return 1
			fi
			worker_ready "$port" || all_ready=false
		done < "$STATE_DIR/workers.tsv"
		$all_ready && return 0
		sleep 2
	done
	echo "workers did not become ready within ${WORKER_READY_TIMEOUT_SECONDS}s" >&2
	while IFS=$'\t' read -r gpu port pid; do
		[[ -n "$gpu" ]] || continue
		worker_status_line "$gpu" "$port" || true
	done < "$STATE_DIR/workers.tsv"
	return 1
}

stop_pid() {
	local pid_file="$1"
	if pid_alive "$pid_file"; then
		kill "$(<"$pid_file")"
		for _ in {1..20}; do pid_alive "$pid_file" || break; sleep 1; done
		pid_alive "$pid_file" && kill -9 "$(<"$pid_file")"
	fi
	rm -f "$pid_file"
}

trim() {
	local value="$1"
	value="${value#"${value%%[![:space:]]*}"}"
	echo "${value%"${value##*[![:space:]]}"}"
}

discover_idle_gpus() {
	local busy_uuids index uuid memory_used utilization uuid_is_busy
	busy_uuids="$(nvidia-smi --query-compute-apps=gpu_uuid --format=csv,noheader,nounits 2>/dev/null || true)"
	while IFS=',' read -r index uuid memory_used utilization; do
		index="$(trim "$index")"
		uuid="$(trim "$uuid")"
		memory_used="$(trim "$memory_used")"
		utilization="$(trim "$utilization")"
		uuid_is_busy=false
		while IFS= read -r busy_uuid; do
			[[ "$uuid" == "$(trim "$busy_uuid")" ]] && uuid_is_busy=true
		done <<< "$busy_uuids"
		if ! "$uuid_is_busy" && (( memory_used <= IDLE_GPU_MAX_MEMORY_MIB && utilization <= IDLE_GPU_MAX_UTILIZATION_PERCENT )); then
			echo "$index"
		fi
	done < <(nvidia-smi --query-gpu=index,uuid,memory.used,utilization.gpu --format=csv,noheader,nounits)
}

start() {
	[[ -x "$PYTHON" ]] || { echo "Python is not executable: $PYTHON" >&2; exit 1; }
	[[ -f "$API" ]] || { echo "Gemma API script not found: $API" >&2; exit 1; }
	[[ -f "$GATEWAY" ]] || { echo "Gateway script not found: $GATEWAY" >&2; exit 1; }
	[[ -d "$MODEL_PATH" ]] || { echo "Model directory not found: $MODEL_PATH" >&2; exit 1; }
	mkdir -p "$STATE_DIR"
	local gpu_list=()
	if [[ "$GPUS" == "auto" ]]; then
		mapfile -t gpu_list < <(discover_idle_gpus | head -n "$REPLICA_COUNT")
		if (( ${#gpu_list[@]} < REPLICA_COUNT )); then
			echo "found ${#gpu_list[@]} idle GPU(s), but REPLICA_COUNT=$REPLICA_COUNT is required" >&2
			echo "Set GPUS=index,index to choose GPUs manually, or adjust the idle thresholds." >&2
			exit 1
		fi
		echo "auto-selected idle GPU(s): $(IFS=,; echo "${gpu_list[*]}")"
	else
		IFS=',' read -r -a gpu_list <<< "$GPUS"
	fi
	local workers=() gpu port index=0
	: > "$STATE_DIR/workers.tsv"
	for gpu in "${gpu_list[@]}"; do
		gpu="${gpu//[[:space:]]/}"
		port=$((WORKER_PORT_BASE + index))
		workers+=("http://127.0.0.1:$port")
		if pid_alive "$STATE_DIR/worker-$gpu.pid"; then
			echo "GPU $gpu worker already running"
		else
			GEMMA4_API_KEY="$API_KEY" nohup "$PYTHON" "$API" --model-path "$MODEL_PATH" --model-name "$MODEL_NAME" --device "cuda:$gpu" --host 127.0.0.1 --port "$port" >"$STATE_DIR/worker-$gpu.log" 2>&1 &
			echo $! >"$STATE_DIR/worker-$gpu.pid"
			echo "started GPU $gpu worker on port $port"
		fi
		local worker_pid=""
		if [[ -f "$STATE_DIR/worker-$gpu.pid" ]]; then worker_pid="$(<"$STATE_DIR/worker-$gpu.pid")"; fi
		printf '%s\t%s\t%s\n' "$gpu" "$port" "$worker_pid" >> "$STATE_DIR/workers.tsv"
		index=$((index + 1))
	done
	if ! wait_for_workers; then
		echo "gateway was not started because at least one worker is unavailable" >&2
		return 1
	fi
	local workers_csv; workers_csv=$(IFS=,; echo "${workers[*]}")
	if ! pid_alive "$STATE_DIR/gateway.pid"; then
		nohup "$PYTHON" "$GATEWAY" --workers "$workers_csv" --host 127.0.0.1 --port "$GATEWAY_PORT" --failure-cooldown-seconds "$GATEWAY_FAILURE_COOLDOWN_SECONDS" >"$STATE_DIR/gateway.log" 2>&1 &
		echo $! >"$STATE_DIR/gateway.pid"
		echo "started gateway on port $GATEWAY_PORT"
	fi
}

stop() {
	stop_pid "$STATE_DIR/gateway.pid"
	for pid_file in "$STATE_DIR"/worker-*.pid; do [[ -e "$pid_file" ]] && stop_pid "$pid_file"; done
}

status() {
	if [[ -f "$STATE_DIR/workers.tsv" ]]; then
		while IFS=$'\t' read -r gpu port pid; do
			[[ -n "$gpu" ]] || continue
			worker_status_line "$gpu" "$port" || true
		done < "$STATE_DIR/workers.tsv"
	else
		echo "worker configuration not found: $STATE_DIR/workers.tsv"
	fi
	if pid_alive "$STATE_DIR/gateway.pid"; then echo "gateway state=running pid=$(<"$STATE_DIR/gateway.pid") port=$GATEWAY_PORT"; else echo "gateway state=stopped port=$GATEWAY_PORT"; fi
	nvidia-smi --query-gpu=index,memory.used,memory.free,utilization.gpu --format=csv,noheader
}

logs() {
	local gpu="${1:-}"
	if [[ -n "$gpu" ]]; then
		local log_file="$STATE_DIR/worker-$gpu.log"
		[[ -f "$log_file" ]] || { echo "worker log not found: $log_file" >&2; return 1; }
		tail -n "${LINES:-100}" "$log_file"
		return
	fi
	tail -n "${LINES:-100}" "$STATE_DIR"/*.log
}
health() {
	if [[ -f "$STATE_DIR/workers.tsv" ]]; then
		while IFS=$'\t' read -r gpu port pid; do
			[[ -n "$gpu" ]] || continue
			worker_status_line "$gpu" "$port" || true
		done < "$STATE_DIR/workers.tsv"
	fi
	"$PYTHON" -c "import urllib.request; print('gateway', urllib.request.urlopen('http://127.0.0.1:${GATEWAY_PORT}/health', timeout=5).read().decode())" 2>&1 || echo "gateway unavailable: port=$GATEWAY_PORT"
}

case "${1:-}" in
	start) start ;;
	stop) stop ;;
	status) status ;;
	logs) logs "${2:-}" ;;
	health) health ;;
	*) usage; exit 2 ;;
esac
