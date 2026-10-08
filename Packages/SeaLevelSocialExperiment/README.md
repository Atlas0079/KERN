# Sea-level social experiment world Package

This Package contains generated world data for the paired 300-Agent sea-level
narrative experiment. `SocialPropagation` remains the capability Package that
owns the screen component, platform effects, recipes, and SQLite adapter.

Regenerate all disposable world, platform, schedule, binding, and manifest
artifacts from the validated 300-profile inputs with:

```powershell
& .\.venv\Scripts\python.exe tools\generate_sea_level_social_experiment.py
```

The source study contract is `Study/study_config.v1.json`. Generation rejects a
population other than 300, missing or duplicate profile IDs, invalid Big Five
values, non-first-person backgrounds, mismatched background IDs, missing or invalid
platform friend categories, unequal paired
ranking topics, invalid network endpoints, and activation plans above the
configured 60-Agent safety threshold.

`population.friend_categories_path` selects `Study/platform_friend_categories.v1.json`.
It contains one `platform_friend_categories` list for every profile ID, with one
to five unique, non-blank categories. These generated persona settings describe
likely platform contacts; they do not create follow edges or prescribe sharing
behavior. `SocialIdentityComponent` carries the required field through catalog
serialization and checkpoints, and the social workflow includes it in identity
context on every page decision.

The two root runtime configs select the same world, network, activation schedule,
background posts, and application-owned `social_platform` workflow provider. They differ
only in their platform seed and artifact paths:

- `runtime_config.sea_level.consequence.json`
- `runtime_config.sea_level.solution.json`

Both configs (including the local 12-tick variants) set the SQLite runtime option
`propagating_post_ids: ["sea_level_experiment_post"]`. Background posts remain
available for ordinary recommendation and all interactions are recorded, but their
reposts are not distributed to followers and their engagement does not boost
recommendation scores. The experimental post retains both mechanisms. Public
interaction counts remain factual. This controls background amplification, not all
background influence, and does not guarantee identical feeds between conditions.
Start a new run with an empty database; retain the old experiment archives.

The experiment rules are documented in `docs/social_platform_experiment_plan.md`;
recommendation details are in `docs/social_platform_runtime_design.md`. The study
JSON holds stimulus/population/network parameters; runtime configs hold this
distribution policy.

Run one condition with:

```powershell
$env:LLM_API_KEY = "..."
& .\.venv\Scripts\python.exe -m applications.social_experiment --config runtime_config.sea_level.consequence.json
```

The social application reads `workflow_providers` and injects a `WorkflowRegistry`
into KERN. Its builder reads schedule, actor bindings, and the stable experimental
post ID from this world's study data. Packages define the world and capabilities;
they do not register decision workflows. The generic `default_orchestrator.py`
entry point supports only the kernel's `simple` and `llm` kinds.

Export raw platform process data after a run with:

```powershell
& .\.venv\Scripts\python.exe tools\export_social_platform_process.py `
  --database KERN\external_runtimes\social_runs\consequence\platform.sqlite `
  --out checkpoints\sea_level_consequence_focus\social_process_export
```

The exporter writes table-level CSV files, exposure and repost process CSV
files, a per-tick summary CSV, and `manifest.json`.
