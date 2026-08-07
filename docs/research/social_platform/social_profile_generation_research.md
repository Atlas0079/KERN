# Social Profile Generation Research

This note summarizes primary-source findings relevant to replacing the current
100-agent social profile generator.

## Problem Framing

KERN needs small synthetic social-platform personas, not a national synthetic
population. The generator still needs the same core property as full synthetic
population tools: internally consistent records. Age, school status, education,
occupation, family status, income pressure, housing, interests, and platform use
should be sampled as coupled fields instead of independent labels.

## Findings

- Synthetic-population literature treats agent attributes as a major driver of
  social-simulation outcomes. The JASSS review defines synthetic populations as
  microscopic records designed to match aggregate statistics of a target
  population, and notes that practice often lags methodology in social
  simulation. Source: https://www.jasss.org/25/2/6.html

- Mature synthetic-population systems often start from census or survey data,
  then reconstruct individuals and households with coherent joint attributes.
  RTI's open repository uses ACS and TIGER data, separates raw/interim/processed
  data, and samples matching households through progressively relaxed matching
  criteria. Source: https://github.com/RTIInternational/rti_synth_pop

- FRED uses a census-derived synthetic population with demographic factors,
  spatial locations, schools, and workplaces. Its description highlights IPF as
  a way to match aggregate demographic tables while keeping individual agents.
  Source: https://fred.publichealth.pitt.edu/fredModel

- SynthPops is an open-source Python package for epidemic ABMs. It generates
  populations and multilayer contact networks, but its README currently says it
  is no longer actively maintained. Source: https://github.com/synthpops/synthpops

- NVIDIA NeMo Data Designer documents two approaches: simple Faker-based people
  for test data, and richer persona datasets with demographic details,
  personality traits, skills, hobbies, and narratives grounded in demographic
  distributions. This supports a useful separation: deterministic structured
  sampling first, narrative generation second. Source:
  https://docs.nvidia.com/nemo/datadesigner/concepts/person-sampling

- Recent LLM-persona work such as ProfileFoundry uses age and education gates
  for occupation sampling, marital-status feasibility rules, salary/finance
  coupling, and post-generation validation of temporal history. It explicitly
  documents those as generator assumptions. Source:
  https://arxiv.org/html/2606.26403v1

- For a China-oriented seed population, official aggregate data can come from
  the National Bureau of Statistics. The 2020 census yearbook includes tables
  by age, sex, education, occupation, marriage, fertility, household, migration,
  and housing; the China Statistical Yearbook provides current annual population
  and employment tables. Sources:
  https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/indexch.htm and
  https://www.stats.gov.cn/sj/ndsj/2025/indexch.htm

## Design Implications For KERN

- Do not use Faker as the main generator. Faker is useful for names and surface
  strings, but it does not enforce cross-field demographic logic.

- Do not rely on LLM prompts to repair contradictions. The LLM should receive
  a validated structured profile and produce text under a no-new-facts rule.

- Use explicit lifecycle stages as the first axis of sampling:
  student, early career, family formation, mid-career, late career, retired.
  Each stage should define allowed age ranges, education states, occupation
  states, household states, and family states.

- Represent hard impossibilities separately from soft rarity. For example:
  "doctoral graduate age 19" is invalid; "40-year-old adult-college student" is
  uncommon but can exist if occupation is not "科研人员" and the education state
  explicitly says continuing/adult education.

- Keep the rule set auditable. Rules should carry IDs and reasons so profile
  reports can show why a combination was blocked, down-weighted, or allowed as
  an outlier.

- Calibrate only the dimensions that matter for the simulation. For a
  social-platform rumor/propagation scenario, platform behavior, media habits,
  trust posture, social ties, topic interest, and life pressure are more
  important than exact national representativeness.
