# Agent Project Memory

This document is the project-level memory for coding agents working on this repository.
It should contain stable facts and current architectural contracts, not task history.

When starting a fresh conversation, read this file first, then inspect the current
working tree and the files directly related to the task. Treat this document as an
index and orientation layer; the code remains the source of truth.

## Start Here

Recommended first checks:

```powershell
git status --short --branch
rg --files
.\venv\Scripts\python.exe --version
```

Use the repository virtual environment on this machine:

```powershell
.\venv\Scripts\python.exe
```

The plain `python` command may not be available in PATH.

Before changing architecture or relying on an interface name, inspect the concrete
implementation with `rg` and file reads. Do not infer interface names from memory.

## Project Shape

KERN is a Python simulation sandbox kernel for data-driven multi-agent scenarios.
It combines ECS-style entity/component world state with discrete event simulation,
declarative recipes/reactions, effect bundles, and optional LLM-driven agent
workflow.

Important top-level paths:

- `default_orchestrator.py`: thin CLI wrapper around `KernRuntime`; reads config and runs until the configured end.
- `KERN/`: core engine package.
- `Data/`: scenario data, entity templates, recipes, reactions, named bundles.
- `docs/`: human-facing design and usage documentation.
- `tools/`: validation, diagnostics, archive inspection, and checkpoint viewer assets.
- `checkpoints/`: generated runtime outputs.

There is a small `unittest` suite under `tests/` for focused contracts such as
dynamic text. Broader runtime/data checks still live in `tools/`.

## Runtime Entry

Main command pattern:

```powershell
.\venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.smoke.json
```

Runtime config files use this shape:

```json
{
  "env": {
    "USE_LLM": "0"
  }
}
```

`default_orchestrator.py` resolves config in this order:

1. `--config`
2. `RUNTIME_CONFIG_FILE`
3. `runtime_config.json`

Common configs:

- `runtime_config.camping.smoke.json`: committed Camping no-LLM smoke/test config.
- `runtime_config.example.json`: committed template for local custom configs.
- `runtime_config.companion_robot.json`: local ignored config name retained for the current kindergarten/phone scenario data.
- `runtime_config.companion_robot.smoke.json`: local ignored no-LLM smoke config name retained for that scenario.

`CompanionRobot` is currently a historical data/config directory name. The active
scenario semantics are shifting to "kindergarten child DouDou who can talk to the
user by phone", not a robot/recycling-station scenario.

Prefer a committed smoke config such as `runtime_config.camping.smoke.json` for
repo-local validation. Use ignored local kindergarten configs only when the task
explicitly needs that scenario behavior.

Runtime configs may contain local API keys or provider tokens. Keep real runtime
config files in `.gitignore`; commit only sanitized examples or templates such as
`runtime_config.example.json`.

## Core Data Flow

Current startup/runtime flow:

1. `default_orchestrator.py` loads runtime config.
2. `KERN.data.loader.load_data_bundle(...)` loads JSON data from `Data/`.
3. Startup validation calls `tools.scenario_lint.lint_bundle(...)` unless skipped.
4. `KERN.data.builder.build_world_state(...)` builds `WorldState`.
5. `KERN.runtime.KernRuntime` acts as the SDK entry point and runtime runner.
6. `TriggerSystem` turns events into reaction effect bundles.
7. `InteractionEngine` compiles agent/user commands through recipes into effect bundles.
8. `WorldExecutor` executes effects and is the write boundary for world mutation.
9. A run archive and `simulation_log.json` are written when checkpointing is enabled.

Architectural boundary: decision logic should not directly mutate `WorldState`.
World writes should go through effects handled by `WorldExecutor`.

Dynamic text rendering lives in `KERN.dynamic_text` and is only applied to explicit
text-output fields. It is strict: unresolved placeholders raise errors instead of
being preserved for compatibility.

## Data Loading Rules

`load_data_bundle(project_root, ...)` finds `Data/` under the repo root, or accepts a
direct `Data/` path.

Loaded data groups:

- `WORLD_JSON`: one world file.
- `RECIPES_JSONS`: comma-separated recipe files; later files update earlier keys.
- `REACTIONS_JSONS`: comma-separated reaction files; `rules` arrays are appended.
- `ENTITIES_DIRS`: directories containing `*.json` templates; files are sorted, later
  keys overwrite earlier keys.
- `BUNDLES_JSONS`: named bundle files; later files update earlier keys.

Current `DataBundle` fields are:

- `entity_templates`
- `recipes`
- `reactions`
- `world`
- `named_bundles`

## Effect System

Effect bundles are normalized by `KERN.effect_bundle.effect_bundle_from_raw`.

Current bundle shape:

```json
{
  "effects": [],
  "react_per_effect": false
}
```

`react_per_effect` is optional and only emitted when true by `EffectBundle.to_dict()`.

Known effect types are declared in `KERN.effect_contract.EFFECT_SPECS`. The executor
resolves binder and handler function names from that contract. Do not add effect
types by only creating handler files; update the contract and validation path.

`WorldExecutor.execute(...)` flow:

1. Bind/normalize effect input with `_effect_binder.bind_effect_input(...)`.
2. Check the effect type against `EFFECT_TYPES`.
3. Resolve the handler through `resolve_effect_handler_callable(...)`.
4. Execute the handler and return event dictionaries.

## Interaction And Workflow

`InteractionEngine.process_command(ws, self_id, command_data)` accepts command data
with:

```json
{
  "verb": "...",
  "target_id": "...",
  "parameters": {}
}
```

It matches recipes by `verb`, `selector`, and `condition`.

Duration/progress recipes produce a `CreateTask` effect. Immediate recipes return
their normalized bundle.

Task lifecycle contract:

- `recipe.process.start_bundle` is optional and is solidified into `Task.start_bundle`.
  It runs whenever a task enters `InProgress`.
- `recipe.process.cleanup_bundle` is optional and is solidified into
  `Task.cleanup_bundle`. It runs whenever a task leaves `InProgress`, including
  successful completion, interrupt/pause, cancel, fail, and resume failure cleanup.
- `recipe.bundle` remains the success-only completion bundle.
- `recipe.progression.tick_bundle` remains the per-worker-tick bundle.

Agent workflow contract is documented in `docs/开发者快速上手.md` and
`docs/配置详解.md`; verify against `KERN/agent_workflow/` before changing it.
Current high-level contract:

```python
mem_patch = workflow.build_memory_patch_data(ws_view, recipe_db, actor_id)
decision = workflow.decide(ws_view, recipe_db, actor_id, reason, mode_context)
```

Runtime applies the memory patch first through `ApplyMemoryPatch`, then calls
`decide(...)`. With the default `WORKFLOW_CONTRACT_ON_ERROR=fail_fast`, missing
required hooks or invalid workflow decisions follow the runtime error/abort path;
`degrade_to_noop` must be configured explicitly to turn contract errors into noops.

Workflow decisions are expected to be dictionaries such as `apply_commands`, `noop`,
or `error`. Runtime-internal compiled operations are not the external workflow
contract.

Runtime boundary note: `KernRuntime` is the KERN SDK entry point and runtime runner. KERN provides a
per-tick scheduling pulse and core capabilities
(load/build/step/condition/recipe/effect/reaction/checkpoint). App layers decide
product orchestration such as scene selection, user dialogue pauses, how user
input becomes memory/events, and UI outbox handling. It is acceptable for KERN to
ask agents each tick whether they need to think; the agent's
DecisionArbiter/interrupt rules/workflow decide whether any thinking or action
actually happens.

## Simulation Loop

`KernRuntime` is the public KERN SDK entry point and runtime runner.

Preferred SDK construction:

```python
from KERN import KernRuntime

runtime = KernRuntime.from_config(project_root, "runtime_config.camping.smoke.json")
runtime.advance_ticks(10)
```

Public runtime APIs:

- `record_initial_state()`: record the current tick without advancing.
- `step()`: advance one tick and return event log records produced in that tick;
  this is low-level and does not record snapshots/checkpoints.
- `step_and_record()`: advance one tick and record snapshot/checkpoint/log output.
- `advance_ticks(count)`: app/server-facing manual advancement API; advances up to
  `count` ticks and returns counts, events, start/end tick, and stop info.
- `run(max_ticks=...)`: batch loop that records initial state and repeatedly calls
  `step_and_record()` until stopped or max ticks is reached.

App layers should use `record_initial_state()`, `advance_ticks(...)`, or
`run(...)`; they should not call private `_capture_snapshot`,
`_save_checkpoint`, or `_save_simulation_log` methods directly.

`KernRuntime.step()` currently:

1. Initializes runtime services on `world_state.services`.
2. Creates a per-tick `RuntimeState`.
3. Advances game time.
4. Records `WorldTickAdvanced`.
5. Dispatches `AdvanceTick` per entity.
6. Uses `TriggerSystem` to build reaction effect bundles.
7. Executes effects through `WorldExecutor`, including chained reactions up to
   `max_trigger_depth`.

Known architectural note in code: `ws.services` is deliberately retained for now;
new service keys should not be spread casually. The comment in
`KERN/runtime.py` points toward a future typed `RuntimeContext` migration.

## Validation Commands

Fast local checks:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_dynamic_text
.\venv\Scripts\python.exe -m compileall KERN tools default_orchestrator.py tests
.\venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.smoke.json
.\venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.example.json
.\venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.smoke.json
```

## Documentation Notes

Some existing Chinese markdown/source files may display mojibake in the current
PowerShell or tool output even when the file bytes are valid UTF-8. Do not assume
the source file is corrupted from `Get-Content` output alone. Before making
documentation-only or encoding fixes, verify the actual file content with an
explicit UTF-8 read, for example:

```powershell
.\venv\Scripts\python.exe -c "from pathlib import Path; print(Path('tools/checkpoint_viewer.html').read_text(encoding='utf-8')[:200])"
```

If Chinese text looks broken in Codex tool output or PowerShell, first suspect
display decoding rather than file corruption. A quick check is to read bytes with
Python and try `utf-8`, `utf-8-sig`, `gbk`/`cp936`, and `latin-1`. In current
repo files, Chinese docs and source strings are generally valid UTF-8; GBK/cp936
often fails with `UnicodeDecodeError`. Do not rewrite or "repair" Chinese text
unless an explicit UTF-8 read confirms the actual file content is corrupted.

When editing Chinese text, read and write files as UTF-8.

This document intentionally uses mostly ASCII headings and identifiers so it remains
readable across shells.

## Agent Working Rules

- Always inspect current code before changing APIs or contracts.
- Reuse existing interfaces and effect types unless there is a clear architectural
  reason to add a new one.
- Keep task-specific conclusions out of this document unless they become stable
  project facts.
- After significant architecture changes, update this file only with durable facts:
  module responsibility, command changes, contract changes, or validation changes.
- Generated checkpoints are runtime outputs; do not treat them as source changes
  unless the task explicitly concerns checkpoint format or viewer behavior.
- Current checkpoint output is a run archive: `manifest.json`,
  `snapshots/snapshot_*.json.gz`, and `deltas/deltas_*.jsonl.gz`. Deltas are
  state-level changes with before/after hashes, not semantic event replay.
- Creating an `ArchiveRecorder` resets the target archive outputs in
  `CHECKPOINT_DIR`. The restore path currently selects an explicit file or the
  latest `snapshots/snapshot_*.json.gz`; it does not auto-materialize arbitrary
  ticks through deltas.
- `tools/checkpoint_viewer_server.py` serves the current archive viewer. It
  discovers archive scenes under `CHECKPOINT_DIR`, materializes
  `snapshots/snapshot_*.json.gz` plus deltas through `KERN.data.archive`, and
  exposes scene/manifest/latest/events/tick APIs for `tools/checkpoint_viewer.html`.
