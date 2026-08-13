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
values, non-first-person backgrounds, mismatched background IDs, unequal paired
ranking topics, invalid network endpoints, and activation plans above the
configured 60-Agent safety threshold.

The two root runtime configs select the same world, network, activation schedule,
background posts, and built-in `social_platform` workflow provider. They differ
only in their platform seed and artifact paths:

- `runtime_config.sea_level.consequence.json`
- `runtime_config.sea_level.solution.json`

Run one condition with:

```powershell
$env:LLM_API_KEY = "..."
& .\.venv\Scripts\python.exe default_orchestrator.py --config runtime_config.sea_level.consequence.json
```

`workflow_providers` selects workflow implementations compiled into the source
tree. It does not import arbitrary factories from config and it does not
discover Package workflows automatically. The `social_platform` builder reads
schedule, actor bindings, and the stable experimental post ID from this world
Package's study data.

Export raw platform process data after a run with:

```powershell
& .\.venv\Scripts\python.exe tools\export_social_platform_process.py `
  --database KERN\external_runtimes\social_runs\consequence\platform.sqlite `
  --out checkpoints\sea_level_consequence_focus\social_process_export
```

The exporter writes table-level CSV files, exposure and repost process CSV
files, a per-tick summary CSV, and `manifest.json`.
