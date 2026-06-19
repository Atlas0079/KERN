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

- `app.py`: runtime entry point.
- `KERN/`: core engine package.
- `Data/`: scenario data, entity templates, recipes, reactions, named bundles.
- `docs/`: human-facing design and usage documentation.
- `tools/`: validation, migration, diagnostics, and legacy checkpoint viewer assets.
- `checkpoints/`: generated runtime outputs.

There is a small `unittest` suite under `tests/` for focused contracts such as
dynamic text. Broader runtime/data checks still live in `tools/`.

## Runtime Entry

Main command pattern:

```powershell
.\venv\Scripts\python.exe companion_server.py --config runtime_config.companion_robot.json
```

Runtime config files use this shape:

```json
{
  "env": {
    "USE_LLM": "0"
  }
}
```

`app.py` resolves config in this order:

1. `--config`
2. `RUNTIME_CONFIG_FILE`
3. `runtime_config.json`

Common configs:

- `runtime_config.json`: current default CompanionRobot config, `USE_LLM=1`.
- `runtime_config.companion_robot.json`: CompanionRobot full config.
- `runtime_config.companion_robot.smoke.json`: CompanionRobot no-LLM smoke config.
- `runtime_config.camping.smoke.json`: Camping no-LLM smoke/test config.
- `runtime_config.example.json`: template for local custom configs.

Prefer `runtime_config.companion_robot.smoke.json` for local validation unless the task explicitly needs real LLM behavior.

Runtime configs may contain local API keys or provider tokens. Keep real runtime
config files in `.gitignore`; commit only sanitized examples or templates such as
`runtime_config.example.json`.

## Core Data Flow

Current startup/runtime flow:

1. `app.py` loads runtime config.
2. `KERN.data.loader.load_data_bundle(...)` loads JSON data from `Data/`.
3. Startup validation calls `tools.scenario_lint.lint_bundle(...)` unless skipped.
4. `KERN.data.builder.build_world_state(...)` builds `WorldState`.
5. `KERN.sim.manager.WorldManager` runs ticks.
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
decision = workflow.decide(ws_view, recipe_db, actor_id, reason, mode_context)
mem_patch = workflow.build_memory_patch_data(ws_view, recipe_db, actor_id)
```

Workflow decisions are expected to be dictionaries such as `apply_commands`, `noop`,
or `error`. Runtime-internal compiled operations are not the external workflow
contract.

## Simulation Loop

`WorldManager.run(max_ticks=...)` records tick 0 into the run archive, writes logs,
then repeatedly calls `step()` until stopped or max ticks is reached.

`WorldManager.step()` currently:

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
`KERN/sim/manager.py` points toward a future typed `RuntimeContext` migration.

## Validation Commands

Fast local checks:

```powershell
.\venv\Scripts\python.exe -m unittest tests.test_dynamic_text
.\venv\Scripts\python.exe -m compileall KERN tools app.py tests
.\venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.companion_robot.smoke.json
.\venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.smoke.json
.\venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.example.json
.\venv\Scripts\python.exe app.py --config runtime_config.companion_robot.smoke.json
```

Useful diagnostic script:

```powershell
.\venv\Scripts\python.exe tools\test_perception_departure_visibility.py
```

`tools\test_gemma4_prompt_styles.py` calls an OpenAI-compatible/Gemini endpoint and
can take a long time or require network/API configuration. Do not treat it as a
normal local health check.

## Documentation Notes

Some existing Chinese markdown/source files may display mojibake in the current
PowerShell or tool output even when the file bytes are valid UTF-8. Do not assume
the source file is corrupted from `Get-Content` output alone. Before making
documentation-only or encoding fixes, verify the actual file content with an
explicit UTF-8 read, for example:

```powershell
.\venv\Scripts\python.exe -c "from pathlib import Path; print(Path('tools/companion_frontend/index.html').read_text(encoding='utf-8')[:200])"
```

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
- `tools/checkpoint_viewer.html` is a legacy uncompressed JSON checkpoint viewer
  and does not directly support current `.json.gz` archive snapshots.
