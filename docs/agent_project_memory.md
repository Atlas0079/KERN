# Agent Project Memory

This document is the project-level orientation note for coding agents working on
this repository. It should describe stable architecture, current contracts, and
useful validation commands. It should not become a task log.

When starting a new task, read this file first, then inspect the actual code and
the files directly related to the request. The code remains the source of truth.

## Current Project Identity

KERN is a Python simulation sandbox kernel for data-driven multi-agent
experiments. The core idea is to keep the simulation world, declarative rules,
effect execution, agent workflow, and checkpoints auditable and replaceable.

KERN is not a single fixed scenario. The repository contains several scenario
datasets and design documents, but the reusable kernel is the main project body.
Scenario names such as `CompanionRobot` are historical data/config labels and
should not be treated as the current product direction unless a task explicitly
targets that data.

Current useful mental model:

```text
runtime config
-> DataBundle
-> WorldState
-> KernRuntime tick loop
-> reactions / workflow / recipes
-> WorldExecutor effects
-> event and interaction logs
-> archive checkpoints
```

Decision logic should not directly mutate `WorldState`. World writes should go
through effect bundles handled by `WorldExecutor`.

## Start Here

Recommended first checks:

```powershell
git status --short --branch
rg --files
```

Use a Python 3.10+ interpreter provided by the user. Prefer an activated virtual
environment; commands in project documentation use the generic `python` name:

```powershell
python --version
```

Before changing an API or relying on an interface name, inspect the concrete
implementation with `rg` and file reads. Do not infer interface names from this
memory document.

## Top-Level Layout

- `default_orchestrator.py`: thin CLI entry point around `KernRuntime`.
- `KERN/`: simulation kernel package.
- `KERN/runtime.py`: SDK/runtime runner, tick loop, service injection,
  checkpoint/archive recording.
- `KERN/models/`: world, entity, component, task, location, path, game time data.
- `KERN/data/`: data loading, world building, checkpoint restore, archive
  materialization.
- `KERN/executor/`: effect binders and handlers plus transaction rollback.
- `KERN/interaction/`: recipe matching and command-to-bundle compilation.
- `KERN/sim/`: trigger/reaction matching and condition evaluation wrapper.
- `KERN/query/`: condition predicates and path/value resolution.
- `KERN/agent_workflow/`: agent perception, memory patching, LLM/simple policies,
  interrupt runtime, workflow contract.
- `KERN/progressors/`: task progression engines, currently including `Linear`.
- `KERN/llm/`: OpenAI-compatible and Gemini client helpers.
- `Data/`: scenario data, shared base recipes/reactions/entities/bundles, and
  scenario subdirectories.
- `docs/`: design notes and human-facing documentation.
- `tools/`: linting, migration, archive viewer, and diagnostics.
- `tests/`: focused unit tests for contracts and regressions.
- `checkpoints/`: generated run archives and logs.

Generated checkpoints, slides outputs, research paper copies, and backups should
not be treated as source changes unless the task explicitly targets them.

## Runtime Entry And Config

Primary CLI pattern:

```powershell
python default_orchestrator.py --config runtime_config.camping.smoke.json
```

Preferred SDK pattern:

```python
from KERN import KernRuntime

runtime = KernRuntime.from_config(project_root, "runtime_config.camping.smoke.json")
runtime.record_initial_state()
runtime.advance_ticks(10)
```

Runtime config files have this shape:

```json
{
  "env": {
    "USE_LLM": "0"
  }
}
```

`KernRuntime.from_config(...)` resolves the config path, loads data, optionally
runs `tools.scenario_lint.lint_bundle(...)`, builds or restores `WorldState`,
selects the action provider, and constructs the runtime.

Important config keys:

- `WORLD_JSON`: world file under `Data/`.
- `RECIPES_JSONS`: comma-separated recipe files.
- `REACTIONS_JSONS`: comma-separated reaction files.
- `ENTITIES_DIRS`: comma-separated entity template directories.
- `BUNDLES_JSONS`: comma-separated named-bundle files.
- `USE_LLM`: selects LLM workflow provider when truthy, otherwise simple policy.
- `MAX_TICKS`: explicit configured run length.
- `CHECKPOINT_DIR`: archive output directory.
- `CHECKPOINT_EVERY_TICK`: enables checkpoint/archive output when truthy.
- `CHECKPOINT_SNAPSHOT_INTERVAL_TICKS`: full snapshot interval for archives.
- `CHECKPOINT_RESTORE_FILE` / `CHECKPOINT_RESTORE_DIR`: restore source.
- `EXTERNAL_RUNTIMES_JSON`: JSON object declaring external runtime adapters.
  The first supported type is `sqlite_social_platform`, with `db_path`,
  optional `reset_db`, and optional `seed_json`.

Committed configs currently include:

- `runtime_config.camping.smoke.json`: no-LLM Camping smoke configuration.
- `runtime_config.rumor_spread.smoke.json`: LLM social rumor-spread smoke
  configuration with a config-declared SQLite social runtime.
- `runtime_config.example.json`: example LLM-enabled config using Farm data.

Runtime configs may contain local credentials. Keep real local configs ignored;
commit only sanitized examples.

## Data Loading And World Building

`KERN.data.loader.load_data_bundle(project_root, ...)` finds `Data/` under the
repo root, or accepts a direct `Data/` path.

Load and merge rules:

- One `WORLD_JSON` is loaded.
- Recipe files are loaded in order; later recipe keys overwrite earlier keys.
- Reaction files are loaded in order; `rules` arrays are appended.
- Entity template directories are scanned for sorted `*.json`; later template
  keys overwrite earlier keys.
- Named bundle files are loaded in order; later keys overwrite earlier keys.

`DataBundle` fields:

- `entity_templates`
- `recipes`
- `reactions`
- `world`
- `named_bundles`

`KERN.data.builder.build_world_state(...)` builds locations, paths,
environment scopes, root entities, nested container entities, initial tasks, and
component instances. Component names unknown to the Python model layer are loaded
as `CustomComponent(data=...)`.

`component_overrides` are applied on top of templates. For `CustomComponent`, the
override is a shallow merge into `data`.

## World And Components

`WorldState` is the main mutable state object:

- `game_time`
- `entities`
- `locations`
- `environment_scopes`
- `tasks`
- `paths`
- `named_bundles`
- `event_log` and `_event_seq`
- `interaction_log` and `_interaction_seq`
- per-tick `services`
- per-tick `runtime_state`

Locations store top-level entity IDs. Nested entities derive physical location
through container ancestry.

Modeled components include:

- `AgentSetting`
- `AgentControlComponent`
- `PlayerControlComponent`
- `LogicControlComponent`
- `DecisionArbiterComponent`
- `MemoryComponent`
- `ContainerComponent`
- `DescriptionComponent`
- `PerceptionComponent`
- `CreatureComponent`
- `StatusComponent`
- `WorkerComponent`
- `TaskHostComponent`
- `EquipmentComponent`
- `EdibleComponent`
- `ValuableComponent`
- `WorldStateEntityComponent`
- `ScreenComponent`
- `TagComponent`

Unknown scenario-defined components are valid and become `CustomComponent`.
Queries and dynamic text can read through `CustomComponent.data` via path
resolution, for example `target.SomeCustomComponent.some_field`.

## Tick Loop

`KernRuntime.step()` currently:

1. Injects per-tick services into `world_state.services`.
2. Creates a fresh `RuntimeState`.
3. Advances game time.
4. Records and dispatches `WorldTickAdvanced`.
5. Records and dispatches `AdvanceTick` once per entity.
6. Sends tick events through `WorldSettlement`.
7. Uses `TriggerSystem` to compile matching reactions into effect bundles.
8. Executes bundles through `WorldExecutor` and processes resulting events in a FIFO queue.
9. Stops the simulation if a reaction fails or exceeds `max_trigger_depth`.
10. Returns event-log records generated during the tick.

Runtime services currently include:

- `interaction_engine`
- `default_action_provider`
- `action_providers`
- `external_runtime_bridge`
- `request_stop`
- `execute`

Avoid spreading new `ws.services` keys casually. The code notes a future typed
runtime context migration.

## Recipes And Interaction

`InteractionEngine.process_command(ws, self_id, command_data)` accepts:

```json
{
  "verb": "...",
  "target_id": "...",
  "parameters": {}
}
```

It matches recipes by:

- exact `verb`
- `selector`
- `condition`

The context passed to effects is:

```json
{
  "self_id": "...",
  "target_id": "...",
  "parameters": {}
}
```

Immediate recipes return a normalized effect bundle. Duration/progress recipes
return a `CreateTask` effect.

Duration recipe contract:

- `process.assign_to` must be `self` or `target`.
- `process.duration` / `required_progress` make a recipe task-like.
- `process.start_bundle` runs when a task enters `InProgress`.
- `process.cleanup_bundle` runs when a task leaves `InProgress`, including
  completion, pause/interrupt, cancel, fail, and resume failure cleanup.
- `recipe.bundle` is the success-only completion bundle.
- `progression.tick_bundle` is the per-worker-tick bundle.
- `process.task_policy` controls interruption behavior.

## Effects And Transactions

Known effect types are declared in `KERN.effect_contract.EFFECT_SPECS`. Adding an
effect means updating the contract and providing a binder/handler module path.
Do not add an effect only by creating a handler file.

Effect input flow:

1. `WorldExecutor.execute(...)`
2. `bind_effect_input(...)`
3. effect-specific `_bind_*`
4. known effect type check
5. handler resolution
6. effect handler execution
7. rollback on execution error

Effect bundles are normalized by `KERN.effect_bundle.effect_bundle_from_raw(...)`
and have this active shape:

```json
{
  "effects": []
}
```

Bundles are the transaction boundary. Successful events are published only after
the whole bundle commits, so reactions observe committed post-bundle state rather
than intermediate state. The removed legacy `react_per_effect` field is not part
of the bundle format.

Transaction contract:

- A single effect is atomic. Handler failure restores the world snapshot from
  before that effect.
- A bundle is atomic. If any effect fails, the world snapshot from before the
  bundle is restored.
- On failure, the returned error event is kept; successful pre-failure events in
  the same bundle are not published as committed world events.

Important built-in effect groups:

- bundle and query: `InvokeBundle`, `RandomBundle`, `ApplyToQuery`
- control/workflow: `AgentControlTick`, `WorkerTick`, `ApplyMetaAction`,
  `AttachDetails`
- entity/location/container: `CreateEntity`, `DestroyEntity`, `MoveEntity`,
  `KillEntity`
- status/property/tags: `ModifyProperty`, `AddTag`, `RemoveTag`, `AddStatus`,
  `RemoveStatus`, `StatusTick`
- tasks: `CreateTask`, `AcceptTask`, `ProgressTask`, `UpdateTaskStatus`,
  `FinishTask`, `InterruptTask`, `InterruptCurrentTask`, `ResumeTask`,
  `CancelTask`, `ConsumeInputs`
- conversation: `StartConversation`
- memory: `AddMemoryNote`, `ApplyMemoryPatch`
- events: `EmitEvent`
- resources/abort: `ExchangeResources`, `AbortSimulation`
- environment: `SetEnvironmentField`, `AddEnvironmentCondition`,
  `RemoveEnvironmentCondition`, `EnvironmentConditionTick`
- social platform: `ObserveSocialFeed`, `ObserveSocialPost`,
  `CreateSocialPost`, `InteractSocialPost`, `FollowSocialAccount`

## Conditions, Queries, And Dynamic Text

Conditions are evaluated through `KERN.query.core.evaluate_predicate(...)`.

Useful predicate types include:

- boolean composition: `all`, `any`, `not`
- entity facts: `has_tag`, `has_tags`, `has_component`, `has_status`
- value comparison: `compare_property`, `compare_value`, `compare_fields`
- inventory: `inventory_contains`, `inventory_has_tag`
- spatial relation: `same_location`
- params/events: `param_eq`, `event_field_eq`
- time: `time_match`, `time_between`, `time_every`
- environment: `environment_field_match`, `environment_has_condition`

Prefer `compare_value` / `compare_fields` when reading nested paths or
`CustomComponent.data`. `compare_property` only reads direct Python attributes on
the component object.

Dynamic text lives in `KERN.dynamic_text`. It renders explicit text-output fields
only. Unresolved placeholders raise `DynamicTextError`; they are not preserved
silently.

Supported dynamic text references include:

- `{self}`, `{target}`, `{event_entity}`
- `{param:name}` and nested `param:` paths
- `{event.foo}`
- `{self.Component.field}`
- `{target.Component.field}`
- `{event_entity.Component.field}`

## Reactions And Semantic Events

`TriggerSystem` matches reaction rules against committed event dictionaries.
Reaction rules may use `on_event`, `selector`, `condition`, and `bundle`.

`KERN.sim.world_settlement.WorldSettlement` owns event publication and reaction
execution. Events are processed FIFO; reactions matching one event execute in
reaction-file order, and their emitted events join the tail of the queue. The
original event has reaction depth 0 and directly triggered reactions have depth
1. Any reaction `BindError`/`ExecutorError`, or an attempt beyond
`max_trigger_depth`, is fatal and stops the simulation. Successful earlier
reaction bundles remain committed; the failing bundle rolls back its own
`WorldState` writes. External runtime writes remain outside this transaction.

Keep raw mechanical events out of agent-facing semantics when possible. If a
low-level state change has narrative meaning, prefer a reaction that emits a
higher-level semantic event via `EmitEvent`, then let memory/workflow decide what
to do with it.

Common raw/control events that should usually not become memories directly:

- `WorldTickAdvanced`
- `AdvanceTick`
- `TaskProgressed`
- `WorkerTick`
- `AgentControlTick`
- `MemoryPatched`
- `MemoryNoteAdded`
- `RandomBundleResolved`
- `ReactionTriggered` / `ReactionApplied`
- ordinary `PropertyModified`
- ordinary status/environment maintenance events

## Agent Workflow

The runtime-facing workflow contract is in `KERN.agent_workflow.runtime` and
`workflow_contract.py`.

Current high-level workflow hooks:

```python
mem_patch = workflow.build_memory_patch_data(ws_view, recipe_db, actor_id)
decision = workflow.decide(ws_view, recipe_db, actor_id, reason, mode_context)
```

The runtime applies the memory patch first through `ApplyMemoryPatch`, then calls
`decide(...)`.

Workflow decisions are dictionaries with types such as:

- `apply_commands`
- `noop`
- `error`

`WORKFLOW_CONTRACT_ON_ERROR` defaults to `fail_fast`. `degrade_to_noop` must be
configured explicitly if contract errors should become noops.

Control components determine which entities enter the decision loop:

- `AgentControlComponent`
- `PlayerControlComponent`
- `LogicControlComponent`

The runtime config builds the default workflow provider:
`SimplePolicyActionProvider` unless `USE_LLM` selects the LLM provider. Optional
`provider_id` values on control components are only routing hints for
`action_providers`; unresolved ids should fall back to the runtime default
provider. RumorSpread currently relies on the runtime default provider and does
not set provider ids in its agent or reaction data.

## Perception And Memory

`build_full_ws_view(...)` creates the workflow view. It includes:

- entities with locations, tags, statuses, descriptions, perception text,
  vitals, memory, task state, inventory, container slots, interrupt settings
- locations with environment fields
- paths
- event and interaction deltas since the actor's memory cursors

`observer.build_agent_perception(...)` turns the full view into an actor-focused
perception structure used by providers.

`MemoryComponent` currently stores:

- `short_term_queue`
- `short_term_max_entries`
- `mid_term_prep_queue`
- `mid_term_prep_max_entries`
- `mid_term_queue`
- `mid_term_max_entries`
- `last_mid_term_summary_tick`
- `mid_term_summary_cooldown_ticks`
- `last_event_seq_seen`
- `last_interaction_seq_seen`

Current memory policy is implemented in `KERN.agent_workflow.memory_policy`.
It filters event and interaction deltas, builds actor-specific memory entries,
and applies them through `ApplyMemoryPatch`.

Short-term memory entries combine initial importance, current weight, age/decay,
created tick, and last accessed tick. Low-scoring entries are pruned. When
`short_term_queue` exceeds its limit, the lowest-scoring entry is evicted; only
entries with enough importance move into `mid_term_prep_queue`. Social feed
exposures may enter short-term memory with very low importance and fast decay,
so they usually disappear after a small number of ticks unless later interaction
makes them salient.

For natural-language-heavy events, a later lightweight LLM scorer may adjust
importance after heuristic filtering. Keep that scorer behind the memory policy
interface; social runtime events should only provide `memory_hint`, not decide
final retention themselves.

## Environment Scopes

`World.json.environment_scopes` defines environment fields and boolean-like
conditions over one or more locations.

Shape:

```json
{
  "scope_id": "camping_region",
  "scope_type": "region",
  "location_ids": ["camp_main", "forest"],
  "priority": 0,
  "fields": {
    "weather": "clear",
    "light_level": 2
  },
  "conditions": ["foggy"],
  "condition_expire_at_tick": {
    "foggy": 60
  }
}
```

`WorldState.get_environment_for_location(location_id)` merges scopes covering a
location by `(priority, scope_id)` order; later scopes overwrite earlier fields.

Weather is a field such as `fields.weather`, not a condition. Conditions should
represent boolean-like facts such as `foggy`, `muddy_ground`, or
`low_visibility`.

Environment write effects:

- `SetEnvironmentField`
- `AddEnvironmentCondition`
- `RemoveEnvironmentCondition`
- `EnvironmentConditionTick`

Environment predicates:

- `environment_field_match`
- `environment_has_condition`

KERN does not provide a special weather scheduler. Use reactions, time
predicates, random bundles, and environment effects.

## Checkpoints And Archives

When checkpointing is enabled, `KernRuntime` creates an `ArchiveRecorder` under
`CHECKPOINT_DIR`.

Archive output currently includes:

- `manifest.json`
- `snapshots/snapshot_*.json.gz`
- `deltas/deltas_*.jsonl.gz`
- `simulation_log.json`

Snapshots store a serialized world dictionary. Deltas are state-level changes
with before/after hashes; they are not semantic replay scripts.

Creating an `ArchiveRecorder` resets the target archive outputs. Do not point it
at a directory whose old contents must be preserved.

Restore path:

- `CHECKPOINT_RESTORE_FILE`, if set and existing
- otherwise latest `snapshots/snapshot_*.json.gz` under
  `CHECKPOINT_RESTORE_DIR`

Restore rebuilds `WorldState` from the snapshot world and reloads logs from the
matching `simulation_log.json` when possible.

Checkpoint serialization includes entity components, including `CustomComponent`.
External runtime adapter internals are not automatically serialized by KERN
unless they are represented in `WorldState` or explicitly integrated into the
archive design.

`tools/checkpoint_viewer_server.py` serves the current archive viewer. It can
materialize snapshots plus deltas through `KERN.data.archive`.

## External Runtime Bridge

External application systems should integrate through explicit domain effects and
`external_runtime_bridge`, not by directly mutating KERN world state.

`KERN.external_runtime.ExternalRuntimeBridge` routes:

```python
bridge.invoke(runtime_id, operation, payload, context)
bridge.poll_events(runtime_id, cursor, context)
```

Adapters should implement:

```python
def invoke(operation: str, payload: dict, context: dict) -> list[dict]:
    ...
```

Returned events must be a list of dictionaries and each dictionary must have a
non-empty `type`. Bridge contract errors are returned as `ExecutorError` events.

`KernRuntime` injects the bridge each tick from `runtime.external_runtimes`.
`from_config(...)` can construct external runtimes from `EXTERNAL_RUNTIMES_JSON`.
The supported social declaration shape is:

```json
{
  "social": {
    "type": "sqlite_social_platform",
    "db_path": "checkpoints/rumor_spread_smoke/social.sqlite3",
    "reset_db": true,
    "seed_json": "Data/RumorSpread/social_seed.json"
  }
}
```

Callers may still pass `external_runtimes={...}` to override or add adapters in
tests and app code.

The social platform runtime currently exists as a SQLite-backed external
runtime:

```text
KERN/external_runtimes/social_platform.py
```

It supports `observe_feed`, `observe_post`, `create_post`, `interact_post`,
`follow_account`, and checkpoint save/restore. Targeted tests live in
`tests/test_social_platform_runtime.py`.

Initial social data can be loaded through
`KERN.external_runtimes.social_seed`. The seed format supports explicit
`accounts`, `posts`, and `follows`, plus lightweight `post_generators` that
expand topic/text rows into deterministic initial posts.

Structured social-account profile generation lives in
`KERN.external_runtimes.social_profile_seed`. It can generate reproducible
profile samples plus LLM background prompts through:

```powershell
python tools\generate_social_profiles.py --count 100 --seed kern-social-profiles-v1
python tools\social_profile_report.py
```

Generated profile outputs are ignored under
`KERN/external_runtimes/social_profiles/`. These profiles are not yet loaded as
KERN agents automatically; a later scenario generator should convert them into
agent entities, carried phone entities, social accounts, interests, and follow
graphs.

The KERN-side integration is intentionally small and screen-driven:

```text
agent -> phone entity -> ScreenComponent -> runtime_id/account_id
-> external_runtime_bridge -> SQLiteSocialPlatformRuntime
```

`ScreenComponent` is mounted on a phone or other terminal entity. Social effects
update that screen with feed cards, the current post, selected post ID, cursor,
and status text. Planner/grounder code should prefer post IDs from
`ScreenComponent.feed_items`, `current_post`, or `selected_post_id` instead of
requiring the agent to remember raw post IDs.

Planner and grounder should receive different projections of that screen state.
Planner-facing context should expose semantic summaries only, such as post title,
author, summary, tags, and social context. Grounder-facing context may expose raw
operational fields such as `post_id`, but only while the screen is fresh. The
first freshness window should be 2 ticks after a social browsing action updates
the phone screen. If the screen context is older than that, grounder should not
reuse stale post IDs and should require a fresh observe action.

Social platform effects currently mutate an external SQLite runtime that is not
rolled back by KERN's `WorldExecutor` bundle rollback. Keep social effects as
single-effect bundles in the first version, or place them last in a bundle. Add
external transaction support later only if this becomes a real consistency
problem.

Do not prioritize device/session access checks yet. The current product choice
is to keep the first version focused on social-media simulation behavior. If
account spoofing, shared devices, or permission problems become real issues,
upgrade the model later with `SocialAppComponent`, `DeviceAccessComponent`, or
session components.

Implemented social effect types are:

- `ObserveSocialFeed`
- `ObserveSocialPost`
- `CreateSocialPost`
- `InteractSocialPost`
- `FollowSocialAccount`

`SocialBehaviorComponent` and `SocialActivityGateTick` provide the current
rumor-spread scene's social activity gate. The gate gives selected agents a
bounded social workflow opportunity without using the default
`AgentControlTick(max_actions=50)` loop. It controls when an agent may act on
the platform; the LLM/provider still decides what action to take. Browsing the
feed (`BrowseSocialFeed`) is treated as free screen refresh. Opening a post,
commenting, liking, reposting, or creating a post consumes social time and
writes `social_action_cooldown` onto the actor through `AddStatus(...,
duration_ticks=2)`. `SocialActivityGateTick` only checks that status; it no
longer reads workflow-internal executed verbs or `SocialBehaviorComponent`
cooldown fields. `fatigue` on `SocialBehaviorComponent` is a reserved field for
a future activity-budget model and is not used by the current gate.

For 100-agent RumorSpread runs, `SocialActivityGateTick` can enable a
scenario-specific batch mode:

```json
{
  "decision_mode": "parallel_decide_serial_commit",
  "max_decision_workers": 16
}
```

This mode is implemented by `KERN.agent_workflow.batch_runtime`. It prepares
workflow inputs serially, calls `workflow.decide(...)` in parallel worker
threads, then validates/compiles/executes outcomes serially in stable actor
order. Worker threads must not mutate `WorldState` or call `WorldExecutor`.

Current social documentation:

- `docs/social_platform_runtime_plan.md`: canonical combined note for the
  external social runtime, phone screen, social effects, recommendation, seed,
  checkpoint behavior, RumorSpread scenario control flow, prompt/agent flow,
  `SocialActivityGateTick`, PHEME seed conversion, intervention and dashboard
  roadmap.
- `docs/social_activity_parallel_decision_plan.md`: design note for
  RumorSpread's scenario-specific parallel LLM decision mode with serial world
  commit.

## Scenario Data Status

The repository contains multiple scenario datasets with different maturity
levels:

- Base data in `Data/Recipes.json`, `Data/Reactions.json`, `Data/Entities/`, and
  `Data/Bundles.json`.
- `Data/Camping/`: committed no-LLM smoke scenario used by
  `runtime_config.camping.smoke.json`.
- `Data/RumorSpread/`: five-agent LLM social rumor-spread scenario used by
  `runtime_config.rumor_spread.smoke.json`. It uses its own reactions,
  `SocialActivityGateTick`, and `WORKFLOW_VIEW_PROFILE=social_platform` to avoid
  embodied same-location perception/memory pollution.
- `Data/Farm/`: example scenario used by `runtime_config.example.json`.
- `Data/SpaceWerewolf/` plus `Data/World_SpaceWerewolf.json`: older/experimental
  scenario data.
- `Data/CompanionRobot/`: historical scenario directory. It may still be useful
  for reference or tests, but it is not the current project center by default.

Do not assume a scenario's design document and JSON data are in perfect sync.
Validate against the actual JSON and runtime behavior.

## Validation Commands

Fast local checks:

```powershell
python -m unittest discover -s tests -p "test_*.py"
python -m compileall KERN tools default_orchestrator.py tests
python tools\scenario_lint.py --config runtime_config.camping.smoke.json
python tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
python tools\scenario_lint.py --config runtime_config.example.json
python default_orchestrator.py --config runtime_config.camping.smoke.json
```

Targeted tests that often matter for architecture work:

```powershell
python -m unittest tests.test_executor_transactions
python -m unittest tests.test_external_runtime_bridge
python -m unittest tests.test_social_platform_runtime
python -m unittest tests.test_rumor_spread_config_runtime
python -m unittest tests.test_archive
python -m unittest tests.test_environment_scopes
python -m unittest tests.test_dynamic_text
python -m unittest tests.test_task_lifecycle
```

## Bounded LLM Smoke Tests

Short DeepSeek v4 pro LLM smoke tests are allowed without asking the user for
separate permission when they are directly relevant to the current agent
workflow change. Treat these as free for project work, but keep them bounded and
explicit:

- State the intended scope before running, such as "two workflow rounds" or "one
  scenario tick".
- State the timeout or expected maximum duration. Prefer short targeted checks
  over long runs.
- Do not use this allowance for long-running full test suites, broad scenario
  sweeps, or open-ended LLM evaluations.
- Report the actual elapsed time and the key behavior observed.

Example accepted scope: run the RumorSpread LLM smoke with `deepseek-v4-pro`
for two workflow rounds, first browsing a carried phone feed and then opening
one visible post from the operable screen context.

## Documentation And Encoding Notes

Some Chinese markdown/source files may display mojibake in PowerShell or Codex
tool output even when the file bytes are valid UTF-8. Do not assume source
corruption from terminal display alone.

Before making encoding fixes, verify actual bytes with an explicit UTF-8 read,
for example:

```powershell
$env:PYTHONIOENCODING='utf-8'
python -c "from pathlib import Path; print(Path('docs/social_platform_runtime_plan.md').read_text(encoding='utf-8')[:200])"
```

This workspace is commonly launched from Windows PowerShell 5.1 with code page
936 and Python stdout defaulting to GBK/CP936. That can make valid UTF-8 Chinese
files look garbled in Codex shell output. For Chinese-heavy reads or Python
commands that print Chinese, normalize the shell output first:

```powershell
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
chcp 65001
$env:PYTHONIOENCODING='utf-8'
```

When editing Chinese text, read and write files as UTF-8.

## Agent Working Rules

- Inspect current code before changing APIs or contracts.
- Reuse existing interfaces and effect types unless there is a clear
  architectural reason to add new ones.
- Keep writes through `WorldExecutor` effects rather than direct decision-layer
  mutation.
- Update `EFFECT_SPECS` and validation paths when adding effect types.
- Keep stable architecture facts in this document; keep task history elsewhere.
- Do not revert user changes in a dirty worktree.
- Treat generated checkpoints and archive outputs as runtime artifacts unless the
  task explicitly targets them.
