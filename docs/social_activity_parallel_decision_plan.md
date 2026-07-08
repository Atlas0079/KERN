# Social Activity Parallel Decision Design

This note records the implemented parallel-decision mechanism for the RumorSpread
social-platform scenario. It is intentionally a scenario-level escape hatch, not
a general KERN tick scheduler redesign.

## Goal

Run social-platform agents with LLM providers without waiting for every LLM
decision serially. The committed 5-agent and generated 100-agent RumorSpread
smoke configs both use this mode explicitly.

The implementation only parallelizes the slow decision call. World writes remain
serial and go through the existing `WorldExecutor` transaction path.

```text
SocialActivityGateTick
-> select eligible social agents serially
-> prepare one workflow input per selected agent serially
-> call workflow.decide(...) in parallel
-> validate, compile, and execute results serially in stable agent order
```

## Non-Goals

- Do not change `KernRuntime.step()`.
- Do not add a general tick phase system.
- Do not execute `WorldExecutor` effects in parallel.
- Do not infer general effect commutativity or conflict freedom.
- Do not make SQLite social runtime writes concurrent.
- Do not replan indefinitely when a serial commit fails.

## Why This Lives Behind An Effect

KERN currently has a serial tick/reaction/effect model. RumorSpread already uses
`SocialActivityGateTick` as a scene-control effect that selects agents and runs
bounded social workflow opportunities. For this milestone, that effect remains
the integration point.

To keep the effect implementation from becoming a large mini-runtime, the batch
logic lives in an agent workflow helper module. The effect gathers social
candidates and calls the helper.

## Interface

The batch helper lives in:

```text
KERN/agent_workflow/batch_runtime.py
```

Current interface:

```python
run_social_activity_batch(
    ws,
    items,
    decision_mode="serial",
    max_decision_workers=1,
) -> list[dict]
```

Each item contains:

```python
{
    "actor_id": "...",
    "workflow": provider,
    "reason": "routine_browse",
    "mode_context": {...},
    "max_actions": 1
}
```

Returned outcomes are in the same order as `items`.

## Decision Modes

`serial`

- Preserve current behavior.
- Run and commit each actor through the existing single-agent social workflow
  path.

`parallel_decide_serial_commit`

- Prepare memory patch and workflow view serially.
- Call `workflow.decide(...)` concurrently.
- Validate, command-compile, apply decision memory notes, and execute operations
  serially in input order.
- Actor failures return an actor-local `error` or `noop` outcome and do not stop
  the whole batch unless the existing workflow policy explicitly aborts the
  simulation during serial commit.

## Important Semantics

- Parallel decisions observe prepared per-actor workflow input from before serial
  commits in the same batch.
- Serial commit order is deterministic: the order emitted by
  `SocialActivityGateTick`, currently sorted by `agent_id`.
- Social cooldown is still recipe-driven. Time-consuming social recipes append
  `AddStatus(self, social_action_cooldown, duration_ticks=2)`.
- `BrowseSocialFeed` is a free screen refresh and should not add cooldown.
- The batch helper must not mutate `WorldState` from worker threads.

## SocialActivityGateTick Parameters

Extend the effect binder with:

```text
decision_mode = "serial"
max_decision_workers = 1
```

Supported `decision_mode` values:

```text
serial
parallel_decide_serial_commit
```

Invalid values degrade to `serial` through `normalize_decision_mode(...)`.

## Acceptance Status

- Existing serial social activity gate tests continue passing.
- `tests/test_social_activity_gate.py` verifies that parallel mode overlaps provider `decide(...)` calls and commits effects in stable actor order.
- Worker threads only call `decide_from_prepared_workflow(...)`; validation, command compilation, operation execution, and `WorldExecutor` writes happen during serial commit.
- A worker exception is converted into an actor-local decision error and committed through the normal workflow decision path.
- `runtime_config.rumor_spread.smoke.json` uses `parallel_decide_serial_commit` with `max_decision_workers=30`.
- `runtime_config.rumor_spread.100agent.smoke.json` points at generated 100-agent data and uses the same decision mode.
