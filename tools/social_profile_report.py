from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.external_runtimes.social_profile_seed import AGE_BANDS, BASE_WEIGHTS, PLATFORM_ARCHETYPES


def _load_profiles(path: Path) -> tuple[str, list[dict[str, Any]]]:
	data = json.loads(path.read_text(encoding="utf-8"))
	if isinstance(data, dict):
		seed = str(data.get("seed", ""))
		raw = data.get("profiles", [])
	elif isinstance(data, list):
		seed = ""
		raw = data
	else:
		raise ValueError("profile input must be a JSON object or array")
	profiles = [dict(x) for x in list(raw or []) if isinstance(x, dict)]
	return seed, profiles


def _sample(profile: dict[str, Any]) -> dict[str, Any]:
	s = profile.get("sample", {}) or {}
	return dict(s) if isinstance(s, dict) else {}


def _specifics(profile: dict[str, Any]) -> dict[str, Any]:
	s = _sample(profile).get("specifics", {}) or {}
	return dict(s) if isinstance(s, dict) else {}


def _display(profile: dict[str, Any]) -> dict[str, str]:
	d = profile.get("display", {}) or {}
	return {str(k): str(v) for k, v in dict(d).items()} if isinstance(d, dict) else {}


def _count_field(profiles: list[dict[str, Any]], field: str) -> dict[str, int]:
	return dict(Counter(str(_sample(p).get(field, "")) for p in profiles if str(_sample(p).get(field, ""))))


def _count_specific(profiles: list[dict[str, Any]], field: str) -> dict[str, int]:
	return dict(Counter(str(_specifics(p).get(field, "")) for p in profiles if str(_specifics(p).get(field, ""))))


def _cross_count(profiles: list[dict[str, Any]], row_field: str, col_field: str) -> dict[str, dict[str, int]]:
	out: dict[str, Counter[str]] = defaultdict(Counter)
	for p in profiles:
		s = _sample(p)
		row = str(s.get(row_field, ""))
		col = str(s.get(col_field, ""))
		if row and col:
			out[row][col] += 1
	return {k: dict(v) for k, v in out.items()}


def _age_stats(profiles: list[dict[str, Any]]) -> dict[str, Any]:
	ages = []
	for p in profiles:
		age = _specifics(p).get("age", None)
		try:
			ages.append(int(age))
		except Exception:
			continue
	if not ages:
		return {"min": None, "max": None, "avg": None}
	return {"min": min(ages), "max": max(ages), "avg": round(sum(ages) / len(ages), 1)}


def _interest_counts(profiles: list[dict[str, Any]], kind: str) -> dict[str, int]:
	counter: Counter[str] = Counter()
	for p in profiles:
		for item in list(_sample(p).get(kind, []) or []):
			if not isinstance(item, dict):
				continue
			label = str(item.get("label", item.get("id", "")) or "")
			if label:
				counter[label] += 1
	return dict(counter)


def _specific_interest_counts(profiles: list[dict[str, Any]], kind: str) -> dict[str, int]:
	counter: Counter[str] = Counter()
	for p in profiles:
		for item in list(_specifics(p).get(kind, []) or []):
			if not isinstance(item, dict):
				continue
			label = str(item.get("specific", item.get("label", "")) or "")
			if label:
				counter[label] += 1
	return dict(counter)


def _flag_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
	flags: list[dict[str, Any]] = []
	for p in profiles:
		s = _sample(p)
		sp = _specifics(p)
		pid = str(p.get("profile_id", ""))
		reasons: list[str] = []
		age = int(sp.get("age", 0) or 0)
		if age >= 35 and s.get("occupation_domain") == "student":
			reasons.append("35+ student domain")
		if s.get("age_band") in {"45-54", "55+"} and s.get("living_situation") == "shared_rental":
			reasons.append("older shared rental")
		if s.get("education") in {"bachelor", "graduate"} and s.get("economic_status") == "affluent" and sp.get("occupation") in {"便利店店员", "餐饮服务员", "社区超市理货员"}:
			reasons.append("affluent high-education frontline service")
		if s.get("economic_status") in {"struggling", "tight"} and s.get("living_situation") == "owned_home":
			reasons.append("tight economy with owned home")
		if reasons:
			flags.append({"profile_id": pid, "reasons": reasons, "summary": str(p.get("summary_line", "")), "specifics": sp})
	return flags


def _target_comparison(distribution: dict[str, int], target: dict[str, float], total: int) -> list[dict[str, Any]]:
	target_total = sum(float(v) for v in target.values()) or 1.0
	rows: list[dict[str, Any]] = []
	for key, weight in target.items():
		observed = int(distribution.get(key, 0))
		observed_pct = observed / total if total else 0.0
		target_pct = float(weight) / target_total
		rows.append(
			{
				"id": key,
				"observed": observed,
				"observed_pct": round(observed_pct, 4),
				"target_pct": round(target_pct, 4),
				"diff_pct_points": round((observed_pct - target_pct) * 100.0, 2),
			}
		)
	return sorted(rows, key=lambda x: abs(float(x["diff_pct_points"])), reverse=True)


def _flag_reason_counts(flags: list[dict[str, Any]]) -> dict[str, int]:
	counter: Counter[str] = Counter()
	for flag in flags:
		for reason in list(flag.get("reasons", []) or []):
			counter[str(reason)] += 1
	return dict(counter)


def build_report_data(seed: str, profiles: list[dict[str, Any]]) -> dict[str, Any]:
	distributions = {
		"platform_archetype": _count_field(profiles, "platform_archetype"),
		"age_band": _count_field(profiles, "age_band"),
		"economic_status": _count_field(profiles, "economic_status"),
		"education": _count_field(profiles, "education"),
		"occupation_domain": _count_field(profiles, "occupation_domain"),
		"social_style": _count_field(profiles, "social_style"),
		"media_style": _count_field(profiles, "media_style"),
		"consumption_style": _count_field(profiles, "consumption_style"),
		"specific_occupation": _count_specific(profiles, "occupation"),
		"specific_living": _count_specific(profiles, "living_situation"),
		"practical_interests": _interest_counts(profiles, "practical_interests"),
		"aspirational_interests": _interest_counts(profiles, "aspirational_interests"),
		"specific_practical_interests": _specific_interest_counts(profiles, "practical_interests"),
		"specific_aspirational_interests": _specific_interest_counts(profiles, "aspirational_interests"),
	}
	flags = _flag_profiles(profiles)
	return {
		"seed": seed,
		"count": len(profiles),
		"age_stats": _age_stats(profiles),
		"distributions": distributions,
		"target_comparison": {
			"platform_archetype": _target_comparison(distributions["platform_archetype"], PLATFORM_ARCHETYPES, len(profiles)),
			"age_band": _target_comparison(distributions["age_band"], AGE_BANDS, len(profiles)),
			"economic_status": _target_comparison(distributions["economic_status"], BASE_WEIGHTS["economic_status"], len(profiles)),
			"occupation_domain": _target_comparison(distributions["occupation_domain"], BASE_WEIGHTS["occupation_domain"], len(profiles)),
		},
		"cross_tabs": {
			"platform_by_age": _cross_count(profiles, "platform_archetype", "age_band"),
			"age_by_occupation": _cross_count(profiles, "age_band", "occupation_domain"),
			"education_by_occupation": _cross_count(profiles, "education", "occupation_domain"),
			"economic_by_living": _cross_count(profiles, "economic_status", "living_situation"),
			"platform_by_media": _cross_count(profiles, "platform_archetype", "media_style"),
		},
		"flags": flags,
		"flag_reason_counts": _flag_reason_counts(flags),
		"samples": [
			{
				"profile_id": str(p.get("profile_id", "")),
				"summary_line": str(p.get("summary_line", "")),
				"sample": _sample(p),
				"specifics": _specifics(p),
				"display": _display(p),
			}
			for p in profiles
		],
	}


def _html_page(data: dict[str, Any]) -> str:
	payload = json.dumps(data, ensure_ascii=False)
	title = "Social Profile Distribution Report"
	return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #f5f7fb; color: #172033; }}
header {{ padding: 18px 24px; background: #ffffff; border-bottom: 1px solid #dbe3ef; position: sticky; top: 0; z-index: 2; }}
h1 {{ margin: 0 0 6px; font-size: 22px; }}
.meta {{ color: #64748b; font-size: 13px; }}
main {{ padding: 18px 24px 40px; }}
.grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }}
.full {{ grid-column: 1 / -1; }}
.card {{ background: #ffffff; border: 1px solid #dbe3ef; border-radius: 8px; padding: 14px; box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06); }}
.card h2 {{ margin: 0 0 12px; font-size: 16px; }}
.bar-row {{ display: grid; grid-template-columns: 180px 1fr 58px; gap: 10px; align-items: center; margin: 7px 0; font-size: 13px; }}
.label {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #334155; }}
.track {{ height: 12px; background: #edf2f7; border-radius: 999px; overflow: hidden; }}
.bar {{ height: 100%; background: #2563eb; border-radius: 999px; }}
.count {{ text-align: right; color: #475569; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ border-bottom: 1px solid #e5edf6; padding: 6px 7px; text-align: right; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: #475569; background: #f8fafc; position: sticky; top: 72px; }}
.flag {{ border-left: 3px solid #dc2626; padding: 8px 10px; background: #fff7f7; margin: 8px 0; font-size: 13px; }}
.sample {{ border-top: 1px solid #e5edf6; padding: 10px 0; font-size: 13px; }}
.sample:first-child {{ border-top: 0; }}
.small {{ color: #64748b; font-size: 12px; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; align-items: center; }}
.controls label {{ display: grid; gap: 4px; color: #475569; font-size: 12px; }}
select {{ border: 1px solid #cbd5e1; border-radius: 6px; padding: 6px 8px; background: white; min-width: 150px; }}
.delta-pos {{ color: #b45309; font-weight: 600; }}
.delta-neg {{ color: #0369a1; font-weight: 600; }}
@media (max-width: 900px) {{ .grid {{ grid-template-columns: 1fr; }} .bar-row {{ grid-template-columns: 130px 1fr 48px; }} }}
</style>
</head>
<body>
<header>
  <h1>Social Profile Distribution Report</h1>
  <div class="meta" id="meta"></div>
</header>
<main>
  <div class="grid" id="cards"></div>
</main>
<script>
const DATA = {payload};
const distNames = {{
  platform_archetype: "平台原型",
  age_band: "年龄段",
  economic_status: "经济状态",
  education: "教育大类",
  occupation_domain: "职业大类",
  specific_occupation: "具体职业",
  social_style: "社交风格",
  media_style: "媒体偏好",
  consumption_style: "消费风格",
  practical_interests: "实操爱好大类",
  aspirational_interests: "观赏/向往兴趣大类"
}};
function entries(obj) {{ return Object.entries(obj || {{}}).sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0], 'zh-Hans-CN')); }}
function card(title, body, cls='') {{ return `<section class="card ${{cls}}"><h2>${{title}}</h2>${{body}}</section>`; }}
function bars(name, obj, limit=20) {{
  const rows = entries(obj).slice(0, limit);
  const max = Math.max(1, ...rows.map(x => x[1]));
  return rows.map(([k,v]) => `<div class="bar-row"><div class="label" title="${{k}}">${{k}}</div><div class="track"><div class="bar" style="width:${{(v/max*100).toFixed(1)}}%"></div></div><div class="count">${{v}}</div></div>`).join('');
}}
function crossTable(tab) {{
  const rows = Object.keys(tab || {{}}).sort();
  const cols = Array.from(new Set(rows.flatMap(r => Object.keys(tab[r] || {{}})))).sort();
  const head = `<tr><th></th>${{cols.map(c => `<th>${{c}}</th>`).join('')}}<th>Total</th></tr>`;
  const body = rows.map(r => {{
    const total = cols.reduce((s,c) => s + (tab[r][c] || 0), 0);
    return `<tr><td>${{r}}</td>${{cols.map(c => `<td>${{tab[r][c] || 0}}</td>`).join('')}}<td>${{total}}</td></tr>`;
  }}).join('');
  return `<div style="overflow:auto; max-height:420px"><table>${{head}}${{body}}</table></div>`;
}}
function targetTable(rows) {{
  const body = (rows || []).map(r => {{
    const cls = r.diff_pct_points >= 0 ? 'delta-pos' : 'delta-neg';
    return `<tr><td>${{r.id}}</td><td>${{(r.target_pct*100).toFixed(1)}}%</td><td>${{r.observed}}</td><td>${{(r.observed_pct*100).toFixed(1)}}%</td><td class="${{cls}}">${{r.diff_pct_points > 0 ? '+' : ''}}${{r.diff_pct_points}}</td></tr>`;
  }}).join('');
  return `<div style="overflow:auto"><table><tr><th>字段值</th><th>基础目标</th><th>实际人数</th><th>实际占比</th><th>偏差百分点</th></tr>${{body}}</table></div><div class="small">这里的目标是基础先验；最终结果会被年龄、职业、平台等条件权重推开，所以它用于校准方向，不是硬性配额。</div>`;
}}
function uniqueValues(field) {{
  return Array.from(new Set((DATA.samples || []).map(s => String((s.sample || {{}})[field] || '')).filter(Boolean))).sort();
}}
function optionList(values) {{
  return '<option value="">全部</option>' + values.map(v => `<option value="${{v}}">${{v}}</option>`).join('');
}}
function sampleMatches(sample) {{
  const platform = document.getElementById('filter-platform')?.value || '';
  const age = document.getElementById('filter-age')?.value || '';
  const economy = document.getElementById('filter-economy')?.value || '';
  const s = sample.sample || {{}};
  return (!platform || s.platform_archetype === platform) && (!age || s.age_band === age) && (!economy || s.economic_status === economy);
}}
function renderSamples() {{
  const matched = (DATA.samples || []).filter(sampleMatches);
  const html = matched.slice(0, 80).map(s => `<div class="sample"><b>${{s.profile_id}}</b> ${{s.summary_line}}<div class="small">${{s.specifics.age}}岁 / ${{s.specifics.education}} / ${{s.specifics.occupation}} / ${{s.specifics.living_situation}} / ${{s.specifics.media_habit}}</div></div>`).join('');
  document.getElementById('sample-list').innerHTML = html || '<div class="small">没有匹配样本。</div>';
  document.getElementById('sample-count').textContent = `${{matched.length}} matched`;
}}
function sampleExplorer() {{
  return `<div class="controls">
    <label>平台<select id="filter-platform">${{optionList(uniqueValues('platform_archetype'))}}</select></label>
    <label>年龄<select id="filter-age">${{optionList(uniqueValues('age_band'))}}</select></label>
    <label>经济<select id="filter-economy">${{optionList(uniqueValues('economic_status'))}}</select></label>
    <span class="small" id="sample-count"></span>
  </div><div id="sample-list"></div>`;
}}
function render() {{
  document.getElementById('meta').textContent = `count=${{DATA.count}} seed=${{DATA.seed || ''}} age=${{DATA.age_stats.min}}-${{DATA.age_stats.max}} avg=${{DATA.age_stats.avg}}`;
  const cards = [];
  for (const [key,title] of Object.entries(distNames)) {{
    cards.push(card(title, bars(key, DATA.distributions[key], key.startsWith('specific') || key.includes('interests') ? 25 : 15)));
  }}
  cards.push(card('基础目标 vs 实际：平台', targetTable(DATA.target_comparison.platform_archetype), 'full'));
  cards.push(card('基础目标 vs 实际：年龄、经济、职业', targetTable([...(DATA.target_comparison.age_band || []), ...(DATA.target_comparison.economic_status || []), ...(DATA.target_comparison.occupation_domain || [])]), 'full'));
  cards.push(card('平台 x 年龄', crossTable(DATA.cross_tabs.platform_by_age), 'full'));
  cards.push(card('年龄 x 职业大类', crossTable(DATA.cross_tabs.age_by_occupation), 'full'));
  cards.push(card('教育 x 职业大类', crossTable(DATA.cross_tabs.education_by_occupation), 'full'));
  cards.push(card('经济 x 居住', crossTable(DATA.cross_tabs.economic_by_living), 'full'));
  const flags = (DATA.flags || []).slice(0, 80).map(f => `<div class="flag"><b>${{f.profile_id}}</b> ${{(f.reasons || []).join(', ')}}<div class="small">${{f.summary}}</div></div>`).join('') || '<div class="small">No flagged combinations.</div>';
  cards.push(card(`待审查组合 (${{(DATA.flags || []).length}})`, bars('flag_reason_counts', DATA.flag_reason_counts, 10) + flags, 'full'));
  cards.push(card('样本筛选预览', sampleExplorer(), 'full'));
  document.getElementById('cards').innerHTML = cards.join('');
  for (const id of ['filter-platform', 'filter-age', 'filter-economy']) {{
    document.getElementById(id).addEventListener('change', renderSamples);
  }}
  renderSamples();
}}
render();
</script>
</body>
</html>"""


def main() -> None:
	parser = argparse.ArgumentParser(description="Create an HTML distribution report for generated social profiles.")
	parser.add_argument("--input", default="checkpoints/generated_social_profiles.json", help="Generated social profiles JSON.")
	parser.add_argument("--output", default="checkpoints/social_profile_distribution_report.html", help="Output HTML path.")
	parser.add_argument("--summary-output", default="checkpoints/social_profile_distribution_summary.json", help="Output summary JSON path.")
	args = parser.parse_args()

	in_path = Path(args.input)
	if not in_path.is_absolute():
		in_path = ROOT / in_path
	out_path = Path(args.output)
	if not out_path.is_absolute():
		out_path = ROOT / out_path
	summary_path = Path(args.summary_output)
	if not summary_path.is_absolute():
		summary_path = ROOT / summary_path

	seed, profiles = _load_profiles(in_path)
	data = build_report_data(seed, profiles)
	out_path.parent.mkdir(parents=True, exist_ok=True)
	summary_path.parent.mkdir(parents=True, exist_ok=True)
	out_path.write_text(_html_page(data), encoding="utf-8")
	summary_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"wrote report: {out_path}")
	print(f"wrote summary: {summary_path}")


if __name__ == "__main__":
	main()
