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
  the complete catalog-serialized state; `components` is a compatibility-only
  core display projection.

`EffectCatalog` is runtime-scoped and shared by lint and executor.
`ComponentCatalog` is runtime-scoped and shared by lint, build, restore,
executor, and archive. Runtime assembly freezes both before execution. A catalog
must not be mutated while a runtime is running.

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
accepts that v2 identity, validates historical v1 directory-hash metadata with
the old rule, and leaves checkpoints without Package metadata on the legacy
path.

Scenario code is not sandboxed and has the same process permissions as KERN.

## Module map

- `KERN/runtime.py`: runtime assembly and tick loop.
- `KERN/data/`: data loading, world construction, checkpoints, archives.
- `KERN/component_catalog/`: component specifications and codecs.
- `KERN/effects/`: effect specifications and catalog.
- `KERN/executor/`: binders, handlers, transactions, rollback.
- `KERN/interaction/`: recipe matching and ActionIntent-to-bundle compilation.
- `KERN/sim/`: reaction settlement, active-turn scheduling, and turn execution.
- `KERN/query/`: condition predicates and path resolution.
- `KERN/agent_workflow/`: perception, memory patching, workflow contracts, registries, and provider adapters.
- `KERN/external_runtime.py` and `KERN/external_runtimes/`: explicit adapters
  for state outside `WorldState`.
- `KERN/failure_report.py`: run-scoped failure evidence and the single
  developer-facing `failure.json`; failure reporting is separate from world
  checkpoints and does not affect world transactions.

## Current runtime constraints

Dynamic text renders once, only in explicitly supported text fields. It is not
a general expression language and does not recursively render values.

## Working rules

- Before proposing a code change, read and understand the relevant code.
- Treat incomplete or unsuitable requests as design questions: identify the
  practical goal, risks, boundaries, and a better implementation path instead
  of blindly following the first formulation.
- Before development, agree with the user on the expected outcome, affected
  area, and acceptance checks. Afterward, explain actual changes, validation,
  difficulties, and tradeoffs.
- Preserve unrelated work in a dirty worktree. Do not reset, checkout, or
  delete user files without explicit scope.
- Use UTF-8 for text reads and writes. On Windows, prefer `.venv\Scripts\python.exe`
  when the `python` command resolves to the Microsoft Store alias.
- Reuse existing interfaces and contracts. Add behavior tests before changing a
  seam or replacing compatibility behavior.
- Tests are not authoritative; kernel contracts are authoritative. Correct
  tests are executable evidence of those contracts. Remove or rewrite tests
  that require behavior which violates an agreed kernel contract.
- Use direct language in documentation and explanations. Avoid rhetorical
  "not X but Y" constructions and unnecessary abstract alternatives; make a
  concrete recommendation that can be implemented.
- Keep stable agent instructions here. Put active, multi-stage designs in a
  dedicated plan; do not use this file as a work log.

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
