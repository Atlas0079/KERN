# Preserved SU7 social-platform research data

This directory preserves the raw inputs from the removed social-platform
implementation. Nothing here is loaded by KERN at runtime.

- `profiles.json`: 100 generated agent profiles and account/entity mappings.
- `social_seed.json`: 111 accounts, 14 posts, and 1,900 follow relationships.
- `World.json`: the former 100-agent and 100-phone instance layout.
- `generated_agents.json`: the former entity templates.
- `scenario_meta.json`: generation provenance and strategy metadata.

The files intentionally retain their legacy component names and scenario
language. They are source material for a future implementation, not a current
KERN package contract.
