from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import (
	GenerationSpec,
	SCHEMA_VERSION,
	default_generation_spec,
	lifecycle_targets_for,
	validate_population,
	validate_profile,
)


DEFAULT_PROFILE_PATH = "KERN/external_runtimes/social_profiles/generated_social_profiles.json"
DEFAULT_REPORT_PATH = "KERN/external_runtimes/social_profiles/social_profile_distribution_report.html"
DEFAULT_SUMMARY_PATH = "KERN/external_runtimes/social_profiles/social_profile_distribution_summary.json"


def _load_profiles(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
		raise ValueError(f"profile input must be a {SCHEMA_VERSION} population object")
	generation = data.get("generation")
	profiles = data.get("profiles")
	if not isinstance(generation, dict) or not isinstance(profiles, list) or any(not isinstance(item, dict) for item in profiles):
		raise ValueError("profile population requires generation metadata and profile objects")
	if int(generation.get("count", -1)) != len(profiles):
		raise ValueError("generation count does not match profile count")
	return dict(generation), [dict(item) for item in profiles]


def _path(profile: Mapping[str, Any], dotted: str) -> Any:
	value: Any = profile
	for part in dotted.split("."):
		if not isinstance(value, Mapping) or part not in value:
			return None
		value = value[part]
	return value


def _distribution(profiles: Iterable[Mapping[str, Any]], dotted: str) -> dict[str, int]:
	return dict(Counter(str(value) for profile in profiles for value in [_path(profile, dotted)] if value is not None and str(value)))


def _cross_tab(profiles: Iterable[Mapping[str, Any]], row_path: str, col_path: str) -> dict[str, dict[str, int]]:
	rows: dict[str, Counter[str]] = defaultdict(Counter)
	for profile in profiles:
		row = _path(profile, row_path)
		col = _path(profile, col_path)
		if row is not None and col is not None:
			rows[str(row)][str(col)] += 1
	return {row: dict(values) for row, values in rows.items()}


def _interest_distribution(profiles: Iterable[Mapping[str, Any]], kind: str) -> dict[str, int]:
	counts: Counter[str] = Counter()
	for profile in profiles:
		for item in list(_path(profile, f"interests.{kind}") or []):
			if isinstance(item, Mapping) and item.get("id"):
				counts[str(item["id"])] += 1
	return dict(counts)


def _education_field_distribution(profiles: Iterable[Mapping[str, Any]]) -> dict[str, int]:
	counts: Counter[str] = Counter()
	for profile in profiles:
		history = list(_path(profile, "education.history") or [])
		if history and isinstance(history[-1], Mapping):
			counts[str(history[-1]["field"])] += 1
	return dict(counts)


def _education_transition_distribution(profiles: Iterable[Mapping[str, Any]], spec: GenerationSpec) -> dict[str, int]:
	counts: Counter[str] = Counter()
	related = spec.config["education_pathways"]["related_fields"]
	for profile in profiles:
		history = list(_path(profile, "education.history") or [])
		for previous, current in zip(history, history[1:]):
			before, after = str(previous["field"]), str(current["field"])
			kind = "same" if before == after else "related" if after in related[before] else "different"
			counts[kind] += 1
	return dict(counts)


def _target_comparison(distribution: Mapping[str, int], targets: Mapping[str, float], total: int) -> list[dict[str, Any]]:
	target_total = sum(float(value) for value in targets.values())
	return [
		{
			"id": key,
			"observed": int(distribution.get(key, 0)),
			"observed_pct": round(int(distribution.get(key, 0)) / total, 4) if total else 0.0,
			"target_pct": round(float(weight) / target_total, 4),
		}
		for key, weight in targets.items()
	]


def build_report_data(seed: str, profiles: list[dict[str, Any]], *, spec: GenerationSpec | None = None) -> dict[str, Any]:
	resolved_spec = spec or default_generation_spec()
	paths = {
		"lifecycle_stage": "demographics.lifecycle_stage",
		"age_band": "demographics.age_band",
		"gender": "demographics.gender",
		"education_completed": "education.highest_completed",
		"education_status": "education.current_status",
		"occupation_status": "occupation.status",
		"occupation_domain": "occupation.domain",
		"economic_pressure": "socioeconomic.economic_pressure",
		"housing": "socioeconomic.housing",
		"consumption_style": "socioeconomic.consumption_style",
		"partnership": "household.partnership",
		"children": "household.children",
		"elder_support": "household.elder_support",
		"family_burden": "household.family_burden",
	}
	distributions = {name: _distribution(profiles, path) for name, path in paths.items()}
	distributions["education_field"] = _education_field_distribution(profiles)
	distributions["education_field_transition"] = _education_transition_distribution(profiles, resolved_spec)
	for kind in ("practical", "aspirational", "high_cost", "science_topics"):
		distributions[f"interests_{kind}"] = _interest_distribution(profiles, kind)
	violations = [
		{"profile_id": str(profile.get("profile_id", "")), "issues": issues}
		for profile in profiles
		for issues in [validate_profile(profile)]
		if issues
	]
	population_violations = validate_population(profiles, resolved_spec)
	ages = [int(_path(profile, "demographics.age")) for profile in profiles]
	traits = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
	personality_means = {
		trait: round(sum(float(_path(profile, f"personality.{trait}")) for profile in profiles) / len(profiles), 3) if profiles else None
		for trait in traits
	}
	return {
		"schema_version": SCHEMA_VERSION,
		"generation": {"seed": seed, "population_id": resolved_spec.population_id, "rule_set": resolved_spec.rule_set, "config_sha256": resolved_spec.config_sha256, "count": len(profiles)},
		"release_gate": {
			"status": "passed" if not population_violations else "failed",
			"hard_violation_count": len(population_violations),
		},
		"age_stats": {"min": min(ages) if ages else None, "max": max(ages) if ages else None, "average": round(sum(ages) / len(ages), 1) if ages else None},
		"personality_means": personality_means,
		"distributions": distributions,
		"target_comparison": {
			"lifecycle_stage": _target_comparison(distributions["lifecycle_stage"], lifecycle_targets_for(resolved_spec), len(profiles)),
		},
		"cross_tabs": {
			"lifecycle_by_education": _cross_tab(profiles, "demographics.lifecycle_stage", "education.highest_completed"),
			"lifecycle_by_occupation_status": _cross_tab(profiles, "demographics.lifecycle_stage", "occupation.status"),
			"education_by_occupation_domain": _cross_tab(profiles, "education.highest_completed", "occupation.domain"),
			"economic_by_housing": _cross_tab(profiles, "socioeconomic.economic_pressure", "socioeconomic.housing"),
			"age_by_children": _cross_tab(profiles, "demographics.age_band", "household.children"),
		},
		"violations": violations,
		"population_violations": population_violations,
		"samples": [
			{
				"profile_id": profile["profile_id"],
				"summary_line": profile["summary_line"],
				"age": _path(profile, "demographics.age"),
				"lifecycle_stage": _path(profile, "demographics.lifecycle_stage"),
				"economic_pressure": _path(profile, "socioeconomic.economic_pressure"),
				"education": _path(profile, "education.description"),
				"occupation": _path(profile, "occupation.description"),
			}
			for profile in profiles
		],
	}


def _html_page(data: Mapping[str, Any]) -> str:
	payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
	return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Social Profile v4 Report</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f4f6fa;color:#172033}}header{{padding:20px 28px;background:white;border-bottom:1px solid #dbe2ed}}main{{padding:20px 28px;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}section{{background:white;border:1px solid #dbe2ed;border-radius:9px;padding:15px}}.full{{grid-column:1/-1}}h1,h2{{margin:0 0 10px}}.ok{{color:#08783e}}.bad{{color:#b42318}}.bar{{display:grid;grid-template-columns:190px 1fr 45px;gap:8px;margin:6px 0;font-size:13px}}.track{{background:#e8eef7;border-radius:8px;overflow:hidden}}.fill{{height:100%;background:#356ae6}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{padding:6px;border-bottom:1px solid #e6ebf2;text-align:right}}td:first-child,th:first-child{{text-align:left}}.sample{{padding:7px 0;border-bottom:1px solid #edf0f5;font-size:13px}}@media(max-width:850px){{main{{grid-template-columns:1fr}}.bar{{grid-template-columns:130px 1fr 35px}}}}
</style></head><body><header><h1>Social Profile v4 Report</h1><div id="meta"></div></header><main id="root"></main>
<script>const D={payload};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function bars(o){{const a=Object.entries(o||{{}}).sort((x,y)=>y[1]-x[1]),m=Math.max(1,...a.map(x=>x[1]));return a.map(([k,v])=>`<div class="bar"><span>${{esc(k)}}</span><span class="track"><span class="fill" style="display:block;width:${{v/m*100}}%"></span></span><b>${{v}}</b></div>`).join('')}}
function table(o){{const rs=Object.keys(o||{{}}),cs=[...new Set(rs.flatMap(r=>Object.keys(o[r])))];return `<div style="overflow:auto"><table><tr><th></th>${{cs.map(c=>`<th>${{esc(c)}}</th>`).join('')}}</tr>${{rs.map(r=>`<tr><td>${{esc(r)}}</td>${{cs.map(c=>`<td>${{o[r][c]||0}}</td>`).join('')}}</tr>`).join('')}}</table></div>`}}
const gate=D.release_gate,root=document.getElementById('root');document.getElementById('meta').innerHTML=`${{D.generation.count}} profiles · seed=${{esc(D.generation.seed)}} · <b class="${{gate.status==='passed'?'ok':'bad'}}">release gate: ${{gate.status}}</b>`;
let out='';for(const [k,v] of Object.entries(D.distributions))out+=`<section><h2>${{esc(k)}}</h2>${{bars(v)}}</section>`;for(const [k,v] of Object.entries(D.cross_tabs))out+=`<section class="full"><h2>${{esc(k)}}</h2>${{table(v)}}</section>`;out+=`<section class="full"><h2>Samples</h2>${{D.samples.map(s=>`<div class="sample"><b>${{esc(s.profile_id)}}</b> ${{esc(s.summary_line)}} — ${{esc(s.education)}} / ${{esc(s.occupation)}}</div>`).join('')}}</section>`;root.innerHTML=out;
</script></body></html>"""


def main() -> None:
	parser = argparse.ArgumentParser(description="Validate and report a social_profile.v4 population.")
	parser.add_argument("--input", default=DEFAULT_PROFILE_PATH)
	parser.add_argument("--output", default=DEFAULT_REPORT_PATH)
	parser.add_argument("--summary-output", default=DEFAULT_SUMMARY_PATH)
	args = parser.parse_args()
	in_path = Path(args.input) if Path(args.input).is_absolute() else ROOT / args.input
	out_path = Path(args.output) if Path(args.output).is_absolute() else ROOT / args.output
	summary_path = Path(args.summary_output) if Path(args.summary_output).is_absolute() else ROOT / args.summary_output
	generation, profiles = _load_profiles(in_path)
	spec = GenerationSpec.from_dict(dict(generation["resolved_config"]))
	if generation.get("config_sha256") != spec.config_sha256 or generation.get("population_id") != spec.population_id:
		raise ValueError("generation metadata differs from embedded resolved_config")
	data = build_report_data(str(generation["seed"]), profiles, spec=spec)
	if data["release_gate"]["status"] != "passed":
		raise ValueError(f"profile release gate failed: {data['violations']}")
	out_path.parent.mkdir(parents=True, exist_ok=True)
	summary_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(_html_page(data), encoding="utf-8")
	summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"wrote report: {out_path}")
	print(f"wrote summary: {summary_path}")


if __name__ == "__main__":
	main()
