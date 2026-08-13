# KERN Agent Guidance

## Project purpose

KERN is a Python simulation kernel for data-driven multi-agent experiments. It
keeps scenario data, decision making, world mutation, and persistence separate
so a run remains inspectable and reproducible.

The core runtime flow is:

```text
runtime config / Package composition
-> data bundle
-> WorldState
-> recipes, workflow, and reactions
-> effect bundles
-> WorldExecutor
-> events and archives
```

Read the relevant implementation before changing an API or relying on this
file. Source code is the final authority.

## Non-negotiable runtime boundaries

- Decision code, workflows, recipes, and reactions do not mutate `WorldState`
  directly. They produce effect bundles; `WorldExecutor` owns world writes.
- Agent dialogue uses the separate `DialoguePolicy` interface. A bounded
  conversation generates its transcript before one child bundle writes each
  utterance through `RecordInteraction`; Event logs are not Agent memory.
- An effect is validated and normalized by its binder before its handler runs.
  Add a core effect through `KERN.effects.EffectSpec`, binder, handler, and
  focused tests together.
- An effect bundle is one world transaction. Any effect failure rolls back the
  containing bundle. Successful events become visible to reactions only after
  the bundle commits.
- External runtime writes are not part of this rollback. Keep them in explicit
  domain effects and avoid placing them before other fallible effects in a bundle.
- `WorldState.services` is an existing string-keyed dependency bag. Reuse its
  current entries; do not add a new key without an explicit design task.

## Design-owner approval boundary

Without explicit approval from the design owner in the current task,
developers, including LLM agents, may modify code only in these extension
areas:

- scenario and capability Packages, including their declared data, components,
  effects, recipes, adapters, configuration, and focused tests;
- `KERN/external_runtimes/` domain runtime implementations and their focused
  tests; and
- new duck-typed Agent Workflow implementations, their domain helpers, and
  focused tests, written against the existing `AgentWorkflow` /
  `AgentTurnSession` contracts. Scenario-specific workflows should live in
  Package or application code.

If a task cannot be completed within these extension areas, stop before editing
and ask the design owner for a decision.

## Components and persistence

Components express entity state and data capabilities. Effects and systems
express world behavior.

`ComponentCatalog` is the single component conversion boundary:

```text
template JSON <-> live component object <-> checkpoint JSON
```

- Build, component overrides, dynamic `CreateEntity`, archive serialization,
  checkpoint restoration, and lint use the same runtime-scoped catalog.
- Ordinary pure-data dataclasses use `DataclassCodec`. Container,
  DecisionArbiter, and TaskHost have dedicated codecs because their nested
  runtime state needs special conversion.
- Unknown component IDs remain compatible as `CustomComponent(data=...)`.
  A registered component must round-trip with its own codec.
- A `TaskHostComponent` codec persists tasks, including their start, tick,
  cleanup, and completion effect bundles. Checkpoints preserve effect data, not
  Python handler code or a catalog itself.
- `KernRuntime.snapshots` uses `runtime_snapshot.v2`. Its `component_state` is
  the complete catalog-serialized state. There is no legacy component projection.

`EffectCatalog` is runtime-scoped and shared by lint and executor.
`ComponentCatalog` is runtime-scoped and shared by lint, build, restore,
executor, and archive. Runtime assembly freezes both before execution. A catalog
must not be mutated while a runtime is running.

LLM network retry is request-scoped. Timeout, connection, 429, and 5xx failures
use bounded exponential backoff; exhaustion is terminal. There is no cross-tick
LLM cooldown. Optional full LLM traces are run artifacts, not world state or
checkpoints.

## Package composition migration status

Phases 0–7 are complete:

- runtime-scoped `EffectCatalog`;
- runtime-scoped `ComponentCatalog` and component codecs;
- Package config, world packages, extension discovery and runtime-scoped
  catalog assembly;
- versioned Package runtime identity and real-scenario regression coverage.

A runtime composes one required world package with any number of capability
packages. Selecting a Package in config means the user trusts its declared code;
there is no separate code-authorization switch. The loader imports only modules
declared by a selected Package's `extensions.py`, registers their marked
definitions into current runtime catalogs, and freezes those catalogs before
execution. `LoadedPackages` fixes a `package_identity.v2` from the manifest,
actual loaded world-data files, and declared extension source files. Restore
requires that exact v2 identity. Historical v1 identities and checkpoints
without Package metadata are rejected.

Scenario code is not sandboxed and has the same process permissions as KERN.

## Module map

- `KERN/runtime.py`: runtime assembly and tick loop.
- `KERN/data/`: data loading, world construction, checkpoints, archives.
- `KERN/component_catalog/`: component specifications and codecs.
- `KERN/effects/`: effect specifications and catalog.
- `KERN/executor/`: binders, handlers, transactions, rollback.
- `KERN/interaction/`: recipe matching, ActionIntent-to-bundle compilation, and
  bounded conversation generation.
- `KERN/sim/`: reaction settlement, active-turn scheduling, and turn execution.
- `KERN/query/`: condition predicates and path resolution.
- `KERN/agent_workflow/`: perception, memory patching, workflow/dialogue
  contracts, registries, provider adapters, and LLM traces.
- `KERN/external_runtime.py` and `KERN/external_runtimes/`: explicit adapters
  for state outside `WorldState`.
- `KERN/failure_report.py`: run-scoped failure evidence and the single
  developer-facing `failure.json`; failure reporting is separate from world
  checkpoints and does not affect world transactions.

## Current runtime constraints

Dynamic text renders once, only in explicitly supported text fields. It is not
a general expression language and does not recursively render values.

## Verification

Run checks proportional to the change. The full local baseline is:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.package.smoke.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.package.smoke.json
```

Run focused tests for the boundary being changed as well, especially executor
transactions, task lifecycle, archives, dynamic text, and external runtimes.
