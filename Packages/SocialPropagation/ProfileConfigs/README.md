# Social profile population configs

`social_profile_generation.v3` configures every stochastic profile dimension. The sampler keeps only cross-field hard constraints and the deterministic sampling algorithm in Python.

The committed configs are:

- `general.json`: complete default configuration and the reference for every field.
- `science_video.json`: an extending configuration that restricts lifecycle, education, and science-topic count.
- `high_education_high_cognition.json`: an extending configuration that creates a highly educated group with higher openness and conscientiousness. It does not claim to measure IQ.

Generate a population with a config:

```powershell
& .\.venv\Scripts\python.exe tools\generate_social_profiles.py `
  --config Packages\SocialPropagation\ProfileConfigs\science_video.json `
  --count 100 `
  --seed experiment-001
```

## Configurable axes

`lifecycle_age_ranges` configures the age range for each lifecycle. `age_sampling` selects uniform sampling or explicit weights for every exact age. `dimensions` configures weights, optional allowed values, and conditional rules for:

- lifecycle quotas and gender distribution;
- completed and current education;
- occupation status and domain;
- partnership, children, elder support, and family burden;
- housing, economic pressure, and consumption style.

`personality` configures the beta-distribution `alpha` and `beta` parameters for all five traits. `details` configures the selection weight of every concrete occupation title. `interests` configures count weights, item weights, and high-cost-interest inclusion probability by economic-pressure level.

`education_pathways` configures subject fields and degree continuity. `field_weights` controls the initial vocational or higher-education field. `transition_weights.master` and `transition_weights.doctorate` control whether the next degree stays in the same field, moves to a declared related field, or crosses to another field. `related_fields` declares the field adjacency graph. A master's profile therefore contains both bachelor and master stages, while a doctorate contains bachelor, master, and doctorate stages. Legitimate field changes remain visible in `education.history`; the top-level education description is derived from its final stage and is never sampled independently.

## Creating another population

Create a sibling file and extend the complete default:

```json
{
  "schema_version": "social_profile_generation.v3",
  "extends": "general.json",
  "population_id": "young_high_education",
  "lifecycle_age_ranges": {
    "student": [18, 24],
    "early_career": [20, 30]
  },
  "dimensions": {
    "demographics.lifecycle_stage": {
      "weights": {
        "student": 0.4,
        "early_career": 0.6,
        "family_formation": 0.0,
        "mid_career": 0.0,
        "late_career": 0.0,
        "retired": 0.0
      }
    "education.highest_completed": {
      "allowed": ["bachelor", "master", "doctorate"]
    }
  }
}
```

Object-valued weight maps in a child config replace the inherited map, so a replacement must state the complete intended distribution. Other objects merge recursively. Arrays replace inherited arrays.

Profiles contain background facts, personality traits, and interests. Platform exposure is experiment configuration. Media preference, information posture, and interaction style are outcomes to infer from situated decisions and run logs; they are deliberately absent from profile configs and LLM source cards.

`allowed` restricts a dimension without changing its underlying weights:

```json
"education.highest_completed": {
  "allowed": ["associate", "bachelor", "master", "doctorate"]
}
```

Conditional rules support scalar equality and the operators `in`, `not_in`, `gte`, `lte`, `gt`, and `lt`. A rule applies exactly one of `multipliers`, `replace_values`, or `replace_weights`. Every rule requires a stable `rule_id` and a reason; applied rules appear in profile audit output.

Configs are strict author-controlled inputs. Unknown fields, unknown option IDs, invalid probabilities, incomplete top-level sections, unsupported predicates, and inheritance outside this directory fail generation. The resolved complete config and its SHA-256 are embedded in `profiles.json`.
