# KERN Agent Guidance

## Project purpose

KERN is a Python simulation kernel for data-driven multi-agent experiments. It
keeps scenario data, decision making, world mutation, and persistence separate
so a run remains inspectable and reproducible.

The core runtime flow is:

```text
runtime config / ScenarioPackage
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
- An effect is validated and normalized by its binder before its handler runs.
  Add a core effect through `KERN.effects.EffectSpec`, binder, handler, and
  focused tests together.
- An effect bundle is one world transaction. Any effect failure rolls back the
  containing bundle. Successful events become visible to reactions only after
  the bundle commits.
- External runtime writes (for example SQLite social-platform writes) are not
  part of this rollback. Keep them in explicit domain effects and avoid placing
  them before other fallible effects in a bundle.
- `WorldState.services` is an existing string-keyed dependency bag. Reuse its
  current entries; do not add a new key without an explicit design task.

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

`EffectCatalog` is runtime-scoped and shared by lint and executor.
`ComponentCatalog` is runtime-scoped and shared by lint, build, restore,
executor, and archive. Runtime assembly freezes both before execution. A catalog
must not be mutated while a runtime is running.

## ScenarioPackage migration status

Phases 0–2 are complete on `laptop`:

- runtime-scoped `EffectCatalog`;
- runtime-scoped `ComponentCatalog` and component codecs;
- behavior and real-scenario regression coverage.

The next work is defined in `docs/scenario_package_migration_plan.md`:

1. load a data-only package from a manifest while retaining legacy config;
2. explicitly authorize and load trusted scenario-owned Effects;
3. explicitly authorize and load trusted pure-data components/codecs;
4. record scenario identity and content version in archives before restore;
5. migrate Camping as the first real package.

Do not implement automatic Python discovery as a side effect of another task.
Trusted scenario code must register its capabilities before catalogs freeze.
Scenario code is not sandboxed and has the same process permissions as KERN.

## Module map

- `KERN/runtime.py`: runtime assembly and tick loop.
- `KERN/data/`: data loading, world construction, checkpoints, archives.
- `KERN/component_catalog/`: component specifications and codecs.
- `KERN/effects/`: effect specifications and catalog.
- `KERN/executor/`: binders, handlers, transactions, rollback.
- `KERN/interaction/`: recipe matching and command-to-bundle compilation.
- `KERN/sim/`: reaction matching and settlement.
- `KERN/query/`: condition predicates and path resolution.
- `KERN/agent_workflow/`: perception, memory patching, providers, workflows.
- `KERN/external_runtime.py` and `KERN/external_runtimes/`: explicit adapters
  for state outside `WorldState`.

## Current scenario-specific constraints

RumorSpread may parallelize LLM `decide(...)` calls only. Preparation and all
world commits remain serial and deterministic; worker threads never mutate
`WorldState` or call `WorldExecutor`.

Dynamic text renders once, only in explicitly supported text fields. It is not
a general expression language and does not recursively render values.

## Working rules

- Before development, agree with the user on outcome, affected area, and
  acceptance checks. Explain actual changes, validation, and tradeoffs after.
- Preserve unrelated work in a dirty worktree. Do not reset, checkout, or
  delete user files without explicit scope.
- Use UTF-8 for text reads and writes. On Windows, prefer `.venv\Scripts\python.exe`
  when the `python` command resolves to the Microsoft Store alias.
- Reuse existing interfaces and contracts. Add behavior tests before changing a
  seam or replacing compatibility behavior.
- Keep stable agent instructions here. Put active, multi-stage designs in a
  dedicated plan; do not use this file as a work log.

## Verification

Run checks proportional to the change. The full local baseline is:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
& .\.venv\Scripts\python.exe -m compileall -q KERN tools default_orchestrator.py tests
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.camping.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.rumor_spread.smoke.json
& .\.venv\Scripts\python.exe tools\scenario_lint.py --config runtime_config.example.json
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.camping.smoke.json
```

Run focused tests for the boundary being changed as well, especially executor
transactions, task lifecycle, archives, dynamic text, external runtimes, and
social activity scheduling when applicable.
