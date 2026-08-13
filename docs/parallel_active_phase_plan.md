# Parallel active phase implementation plan

## Goal

Add a replaceable active-phase execution layer so KERN can keep the current
serial turn behavior while allowing an opt-in parallel decision mode for the
social-platform experiment.

The first implementation targets the sea-level social-platform scenario:
Agents in the same tick may make page decisions concurrently, while all action
resolution, EffectBundle execution, reactions, checkpoints, and external
runtime commits remain serial.

## Current code path

The current active phase is hard-wired in `KERN.runtime.KernRuntime._step()`:

```text
KernRuntime._step()
-> WorldSettlement(...)
-> TurnScheduler.run_active_phase(ws, settlement)
-> TurnRunner.run(...) per actor
-> session.next_step(ws, frame)
-> resolve_action_intent(...)
-> settlement.execute_bundle(...)
```

Important implementation facts:

- `TurnScheduler.run_active_phase()` sorts all controlled entity IDs and grants
  turns with a normal `for` loop.
- `TurnRunner.run()` owns one Agent turn and loops through
  `next_step -> resolve -> execute_bundle -> feedback`.
- `WorldSettlement` and `WorldExecutor` are serial write boundaries. The
  executor keeps mutable bundle transaction state and must not be called from
  multiple threads.
- `WorkflowRegistry.resolve()` returns workflow instances; `begin_turn()`
  creates an independent session per actor.
- `SocialPlatformWorkflow` active sessions first submit `BrowseSocialFeed`.
  After the browse feedback commits, the session consumes record inbox into
  memory, may consolidate memory, and then calls the LLM for page decision.
- `LLMTraceRecorder` already protects trace writes with a lock.

## Design

Introduce an active-phase strategy layer:

```text
KERN/sim/active_phase.py
  ActivePhaseMode
  SerialActivePhaseStrategy
  ParallelBatchActivePhaseStrategy
```

`SerialActivePhaseStrategy` preserves the existing behavior by delegating to the
current `TurnScheduler`.

`ParallelBatchActivePhaseStrategy` runs active turns in deterministic batches:

```text
1. Collect eligible turns in the same sorted order as TurnScheduler.
2. begin_turn() each selected workflow serially.
3. Advance all live sessions in rounds.
4. Run decision calls concurrently only when the round is safe for parallel
   execution.
5. Resolve and commit returned SubmitAction steps on the main thread in
   turn_index order.
6. Feed each session the committed or rejected ActionFeedback in the next round.
7. End the tick when all sessions return EndTurn, become ineligible, hit a
   budget, or the runtime aborts.
```

The first version will parallelize social page-decision calls after
`BrowseSocialFeed` has committed for each active Agent. It will not parallelize
world writes or generic memory patch execution.

## Social workflow adjustment

The existing social session performs memory patching and possible memory
consolidation immediately before the LLM decision. That code can write
`WorldState`, so it must stay on the main thread.

To keep the first parallel runner simple and safe, split the social session's
post-browse phase into:

```text
serial preparation:
  apply_record_memory_patch(...)
  consolidate_memory_if_needed(...)
  build page-decision request data

parallel wait:
  client.chat_text(...)

serial completion:
  parse/validate response
  record trace
  convert validated output to action intents
```

The public `AgentWorkflow` / `AgentTurnSession` contract remains unchanged.
Serial mode continues to call `session.next_step()` exactly as before.

The parallel runner may use a small social-specific helper on
`SocialPlatformWorkflow` or its active session for this first milestone. This is
an implementation shortcut for the current experiment, not the final generic
parallel-planning abstraction.

## Configuration

Add optional runtime config keys:

```text
ACTIVE_PHASE_MODE=serial | parallel_batch
PARALLEL_DECISION_WORKERS=<positive integer>
```

Default mode is `serial`, preserving current behavior for all existing configs.

The sea-level experiment configs can opt into:

```json
"ACTIVE_PHASE_MODE": "parallel_batch",
"PARALLEL_DECISION_WORKERS": "16"
```

## Allowed files for this task

Implementation may modify only:

- `docs/parallel_active_phase_plan.md`
- `KERN/runtime.py`
- `KERN/sim/turn_scheduler.py`
- `KERN/sim/turn_runner.py`
- `KERN/sim/active_phase.py`
- `KERN/agent_workflow/social_platform.py`
- focused tests under `tests/runtime/` and `tests/agent/`
- sea-level runtime configs if needed to opt into the new mode

If implementation requires changes outside this list, stop and ask for design
owner approval.

## Tests and checks

Focused checks:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.runtime.test_turn_scheduler tests.agent.test_social_platform_workflow
```

Social-platform checks:

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.runtime.test_social_platform_runtime tests.runtime.test_social_package_effects tests.runtime.test_social_screen_component tests.agent.test_social_platform_workflow
```

Config checks:

```powershell
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.sea_level.consequence.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.sea_level.solution.json
```

## Acceptance

- Existing serial mode remains behavior-compatible with current tests.
- Parallel batch mode can start multiple active social sessions in one tick.
- Active social sessions all browse before their LLM page decisions are issued.
- LLM page-decision calls run concurrently in parallel batch mode.
- All returned actions are committed serially in deterministic turn order.
- Rejections, action budget, replan budget, abort, and long-task turn ending keep
  the same semantics as serial mode.
- No `WorldExecutor` or `WorldSettlement` call is made from worker threads.
