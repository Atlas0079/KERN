from __future__ import annotations

import argparse
import html
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_CLASSES = {
	"incident_initial": ["incident_initial"],
	"unverified_claim": ["unverified_claim"],
	"technical_explanation": ["technical_explanation"],
	"empathy_response": ["empathy_response"],
	"expert_context": ["expert_context"],
	"official_investigation": ["official_investigation"],
	"platform_label": ["platform_label"],
	"background": ["background"],
}

CLASS_LABELS = {
	"incident_initial": "事故初始信息",
	"unverified_claim": "未证实归因/质疑",
	"technical_explanation": "技术解释",
	"empathy_response": "情绪与善后回应",
	"expert_context": "专家/第三方解释",
	"official_investigation": "调查进展",
	"platform_label": "平台提示",
	"background": "背景讨论",
	"other": "其他",
}


def _load_json(path: Path | None) -> dict[str, Any]:
	if path is None or not path.exists():
		return {}
	data = json.loads(path.read_text(encoding="utf-8"))
	return dict(data) if isinstance(data, dict) else {}


def _resolve(base: Path, value: str) -> Path | None:
	raw = str(value or "").strip()
	if not raw:
		return None
	path = Path(raw)
	if not path.is_absolute():
		path = base / path
	return path.resolve()


def _connect(db_path: Path | None) -> sqlite3.Connection | None:
	if db_path is None or not db_path.exists():
		return None
	conn = sqlite3.connect(str(db_path))
	conn.row_factory = sqlite3.Row
	return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
	return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _class_for_tags(tags: set[str], class_map: dict[str, list[str]]) -> str:
	for cls, needles in class_map.items():
		if tags & {str(x) for x in list(needles or [])}:
			return str(cls)
	return "other"


def _post_classes_from_rows(posts: list[dict[str, Any]], class_map: dict[str, list[str]]) -> dict[str, str]:
	out = {}
	for post in posts:
		pid = str(post.get("post_id", "") or "")
		if not pid:
			continue
		tags = {str(x) for x in list(post.get("tags", []) or [])}
		out[pid] = _class_for_tags(tags, class_map)
	return out


def _post_classes_from_db(conn: sqlite3.Connection, class_map: dict[str, list[str]]) -> dict[str, str]:
	out = {}
	if not _table_exists(conn, "posts"):
		return out
	rows = conn.execute(
		"""
		SELECT p.post_id, GROUP_CONCAT(pt.tag) AS tags
		FROM posts p
		LEFT JOIN post_tags pt ON pt.post_id=p.post_id
		GROUP BY p.post_id
		"""
	).fetchall()
	for row in rows:
		pid = str(row["post_id"] or "")
		tags = {x.strip() for x in str(row["tags"] or "").split(",") if x.strip()}
		out[pid] = _class_for_tags(tags, class_map)
	return out


def _seed_posts(seed: dict[str, Any]) -> list[dict[str, Any]]:
	return [dict(x) for x in list(seed.get("posts", []) or []) if isinstance(x, dict)]


def _profiles_by_account(profiles_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
	profiles = {str(p.get("profile_id", "")): dict(p) for p in list(profiles_payload.get("profiles", []) or []) if isinstance(p, dict)}
	out = {}
	for row in list(profiles_payload.get("profile_accounts", []) or []):
		if not isinstance(row, dict):
			continue
		account_id = str(row.get("account_id", "") or "")
		profile_id = str(row.get("profile_id", "") or "")
		if account_id and profile_id in profiles:
			out[account_id] = profiles[profile_id]
	return out


def _profile_group(profile: dict[str, Any], field: str) -> str:
	sample = dict(profile.get("sample", {}) or {}) if isinstance(profile, dict) else {}
	display = dict(profile.get("display", {}) or {}) if isinstance(profile, dict) else {}
	if field == "specific_occupation":
		return str(dict(sample.get("specifics", {}) or {}).get("occupation", "") or "unknown")
	return str(display.get(field, sample.get(field, "")) or "unknown")


def _empty_metrics(class_map: dict[str, list[str]]) -> dict[str, dict[str, int]]:
	classes = [*class_map.keys(), "other"]
	return {cls: {"posts": 0, "exposures": 0, "exposed_accounts": 0, "views": 0, "view_accounts": 0, "likes": 0, "comments": 0, "reposts": 0} for cls in classes}


def build_data(run_dirs: list[Path], seed_path: Path | None, profiles_path: Path | None, class_map: dict[str, list[str]]) -> dict[str, Any]:
	seed = _load_json(seed_path)
	profiles_payload = _load_json(profiles_path)
	posts = _seed_posts(seed)
	seed_post_classes = _post_classes_from_rows(posts, class_map)
	profiles_by_account = _profiles_by_account(profiles_payload)
	runs = []
	for run_dir in run_dirs:
		db_path = run_dir / "social.sqlite3"
		conn = _connect(db_path)
		post_classes = dict(seed_post_classes)
		metrics = _empty_metrics(class_map)
		by_tick_class: Counter[tuple[int, str]] = Counter()
		by_group_class: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
		top_posts: Counter[str] = Counter()
		operations: Counter[str] = Counter()
		has_db = conn is not None
		try:
			if conn is not None:
				post_classes.update(_post_classes_from_db(conn, class_map))
				for cls in post_classes.values():
					metrics.setdefault(cls, {"posts": 0, "exposures": 0, "exposed_accounts": 0, "views": 0, "view_accounts": 0, "likes": 0, "comments": 0, "reposts": 0})
					metrics[cls]["posts"] += 1
				if _table_exists(conn, "exposures"):
					account_sets: dict[str, set[str]] = defaultdict(set)
					for row in conn.execute("SELECT account_id, post_id, tick FROM exposures").fetchall():
						pid = str(row["post_id"] or "")
						aid = str(row["account_id"] or "")
						cls = post_classes.get(pid, "other")
						metrics.setdefault(cls, dict(_empty_metrics({cls: []})[cls]))
						metrics[cls]["exposures"] += 1
						account_sets[cls].add(aid)
						by_tick_class[(int(row["tick"] or 0), cls)] += 1
						top_posts[pid] += 1
						profile = profiles_by_account.get(aid, {})
						for field in ["platform_archetype", "age_band", "media_style", "occupation_domain"]:
							by_group_class[field][(_profile_group(profile, field), cls)] += 1
					for cls, values in account_sets.items():
						metrics[cls]["exposed_accounts"] = len(values)
				for table, metric, account_col in [
					("view_history", "views", "account_id"),
					("likes", "likes", "account_id"),
					("comments", "comments", "author_id"),
					("reposts", "reposts", "account_id"),
				]:
					if not _table_exists(conn, table):
						continue
					account_sets: dict[str, set[str]] = defaultdict(set)
					for row in conn.execute(f"SELECT {account_col} AS account_id, post_id FROM {table}").fetchall():
						pid = str(row["post_id"] or "")
						aid = str(row["account_id"] or "")
						cls = post_classes.get(pid, "other")
						metrics.setdefault(cls, dict(_empty_metrics({cls: []})[cls]))
						metrics[cls][metric] += 1
						if metric == "views":
							account_sets[cls].add(aid)
					if metric == "views":
						for cls, values in account_sets.items():
							metrics[cls]["view_accounts"] = len(values)
				if _table_exists(conn, "action_traces"):
					for row in conn.execute("SELECT operation, COUNT(*) AS c FROM action_traces GROUP BY operation").fetchall():
						operations[str(row["operation"] or "")] = int(row["c"] or 0)
			else:
				for post in posts:
					cls = seed_post_classes.get(str(post.get("post_id", "") or ""), "other")
					metrics.setdefault(cls, dict(_empty_metrics({cls: []})[cls]))
					metrics[cls]["posts"] += 1
					by_tick_class[(int(post.get("tick", 0) or 0), cls)] += 0
		finally:
			if conn is not None:
				conn.close()
		runs.append(
			{
				"label": run_dir.name,
				"run_dir": str(run_dir),
				"has_db": has_db,
				"metrics": metrics,
				"by_tick_class": [{"tick": tick, "class": cls, "count": count} for (tick, cls), count in sorted(by_tick_class.items())],
				"by_group_class": {
					field: [{"group": group, "class": cls, "count": count} for (group, cls), count in sorted(counter.items())]
					for field, counter in by_group_class.items()
				},
				"top_posts": [{"post_id": pid, "exposures": count, "class": post_classes.get(pid, "other")} for pid, count in top_posts.most_common(12)],
				"operations": dict(operations),
			}
		)
	return {
		"scenario": str(seed.get("scenario", "")) or "social_event",
		"strategy": str(seed.get("strategy", "")) or str(profiles_payload.get("strategy", "")),
		"class_labels": CLASS_LABELS,
		"class_map": class_map,
		"seed_posts": posts,
		"profiles_count": int(profiles_payload.get("count", len(profiles_payload.get("profiles", []) or [])) or 0),
		"profile_distributions": _profile_distributions(list(profiles_payload.get("profiles", []) or [])),
		"runs": runs,
	}


def _profile_distributions(profiles: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
	out: dict[str, Counter[str]] = defaultdict(Counter)
	for p in profiles:
		for field in ["platform_archetype", "age_band", "media_style", "occupation_domain", "economic_status"]:
			out[field][_profile_group(dict(p), field)] += 1
	return {field: dict(counter) for field, counter in out.items()}


def _html(data: dict[str, Any]) -> str:
	payload = json.dumps(data, ensure_ascii=False)
	return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Social Event Simulation Dashboard</title>
<style>
:root {{ --bg:#f4f6f8; --panel:#ffffff; --ink:#17211d; --muted:#68746f; --line:#d8dfda; --moss:#2d5a4b; --sage:#739a83; --clay:#b16e45; --blue:#3b6f9e; --red:#b45353; --amber:#c08a32; --violet:#6f5aa8; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI", "Microsoft YaHei", system-ui, sans-serif; background:var(--bg); color:var(--ink); }}
header {{ padding:18px 24px; background:#17211d; color:white; display:flex; justify-content:space-between; gap:20px; align-items:flex-end; }}
h1 {{ margin:0; font-size:22px; letter-spacing:0; }}
.sub {{ color:#d8e2dc; font-size:13px; margin-top:5px; }}
main {{ padding:18px 22px 34px; display:grid; gap:16px; }}
.grid {{ display:grid; grid-template-columns:repeat(12, minmax(0,1fr)); gap:14px; }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px; box-shadow:0 10px 24px rgba(23,33,29,.06); min-width:0; }}
.span-3 {{ grid-column:span 3; }} .span-4 {{ grid-column:span 4; }} .span-5 {{ grid-column:span 5; }} .span-7 {{ grid-column:span 7; }} .span-8 {{ grid-column:span 8; }} .span-12 {{ grid-column:span 12; }}
h2 {{ margin:0 0 12px; font-size:15px; }}
.kpi {{ display:grid; gap:4px; min-height:82px; }}
.kpi .value {{ font-size:26px; font-weight:700; color:var(--moss); }}
.kpi .label {{ font-size:12px; color:var(--muted); }}
.kpi .hint {{ font-size:11px; color:#87928d; }}
.chart {{ width:100%; overflow:hidden; }}
.chart svg {{ width:100%; height:auto; display:block; }}
.legend {{ display:flex; flex-wrap:wrap; gap:7px 12px; margin-top:10px; color:#56635d; font-size:11px; }}
.legend span {{ display:inline-flex; align-items:center; gap:5px; }}
.swatch {{ width:10px; height:10px; border-radius:2px; display:inline-block; }}
.insight-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:10px; }}
.insight {{ background:#f8faf9; border:1px solid #edf1ee; border-radius:7px; padding:9px; }}
.insight b {{ display:block; font-size:16px; color:#25483d; }}
.insight span {{ display:block; color:var(--muted); font-size:11px; margin-top:2px; }}
.heatmap {{ display:grid; gap:6px; }}
.heat-row {{ display:grid; grid-template-columns:120px repeat(8, minmax(42px,1fr)); gap:4px; align-items:stretch; font-size:11px; }}
.heat-label {{ color:#405048; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; padding-top:5px; }}
.heat-cell {{ min-height:28px; border-radius:5px; display:flex; align-items:center; justify-content:center; color:#18342b; font-weight:600; }}
.heat-head {{ color:#68746f; text-align:center; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.class-cards {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }}
.class-card {{ border:1px solid #e6ece8; border-radius:7px; padding:10px; background:#fbfcfb; min-width:0; }}
.class-card .name {{ font-weight:700; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.class-card .big {{ font-size:22px; color:#25483d; font-weight:700; margin-top:4px; }}
.class-card .meta {{ color:var(--muted); font-size:11px; margin-top:2px; }}
.timeline {{ display:flex; gap:8px; align-items:stretch; overflow:auto; padding-bottom:4px; }}
.stage {{ min-width:185px; border:1px solid var(--line); border-radius:7px; padding:10px; background:#fbfcfb; }}
.stage .tick {{ color:var(--moss); font-weight:700; font-size:12px; }}
.stage .cls {{ font-weight:700; margin:4px 0; font-size:13px; }}
.stage .text {{ color:#405048; font-size:12px; line-height:1.45; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ border-bottom:1px solid #edf1ee; padding:7px 8px; text-align:right; white-space:nowrap; }}
th:first-child,td:first-child {{ text-align:left; }}
th {{ color:#51605a; background:#f8faf9; }}
.bar-row {{ display:grid; grid-template-columns:150px 1fr 48px; gap:8px; align-items:center; margin:7px 0; font-size:12px; }}
.bar-label {{ overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#31413b; }}
.track {{ height:11px; border-radius:999px; background:#edf1ee; overflow:hidden; }}
.bar {{ height:100%; border-radius:999px; background:var(--sage); }}
.note {{ color:var(--muted); font-size:12px; line-height:1.5; }}
.tag {{ display:inline-block; padding:3px 7px; border-radius:999px; background:#e8f0eb; color:#25483d; font-size:11px; margin:2px; }}
.warn {{ color:var(--red); font-weight:700; }}
.empty {{ color:var(--muted); padding:14px; background:#f8faf9; border-radius:6px; }}
@media (max-width:1000px) {{ .span-4,.span-5,.span-7,.span-8,.span-12 {{ grid-column:span 12; }} .span-3 {{ grid-column:span 6; }} header {{ display:block; }} .class-cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .insight-grid {{ grid-template-columns:1fr; }} }}
@media (max-width:620px) {{ .span-3 {{ grid-column:span 12; }} .class-cards {{ grid-template-columns:1fr; }} .heat-row {{ grid-template-columns:96px repeat(8, minmax(34px,1fr)); }} }}
</style>
</head>
<body>
<header>
  <div>
    <h1>Social Event Simulation Dashboard</h1>
    <div class="sub" id="subtitle"></div>
  </div>
  <div class="sub">prototype dashboard · static HTML</div>
</header>
<main id="app"></main>
<script>
const DATA = {payload};
const labelOf = c => (DATA.class_labels && DATA.class_labels[c]) || c;
const COLORS = {{
 incident_initial:'#3b6f9e', unverified_claim:'#b45353', technical_explanation:'#2d5a4b', empathy_response:'#c08a32',
 expert_context:'#6f5aa8', official_investigation:'#4f8f72', platform_label:'#73808a', background:'#9bb6a5', other:'#b8a58a'
}};
const keyClasses = ['incident_initial','unverified_claim','technical_explanation','empathy_response','official_investigation','platform_label','background','other'];
const fmt = n => Number(n || 0).toLocaleString('zh-CN');
function metric(run, key) {{ return Object.values(run.metrics || {{}}).reduce((s,m)=>s+(m[key]||0),0); }}
function panel(title, body, span='span-12') {{ return `<section class="panel ${{span}}"><h2>${{title}}</h2>${{body}}</section>`; }}
function kpi(value,label,hint='') {{ return `<div class="panel span-3 kpi"><div class="value">${{fmt(value)}}</div><div class="label">${{label}}</div>${{hint ? `<div class="hint">${{hint}}</div>` : ''}}</div>`; }}
function table(rows, cols) {{
 if(!rows.length) return '<div class="empty">No rows yet. Run the simulation to populate this panel.</div>';
 return `<table><tr>${{cols.map(c=>`<th>${{c.label}}</th>`).join('')}}</tr>${{rows.map(r=>`<tr>${{cols.map(c=>`<td>${{r[c.key] ?? ''}}</td>`).join('')}}</tr>`).join('')}}</table>`;
}}
function bars(obj, limit=12) {{
 const rows = Object.entries(obj||{{}}).sort((a,b)=>b[1]-a[1]).slice(0,limit);
 const max = Math.max(1, ...rows.map(x=>x[1]));
 return rows.map(([k,v])=>`<div class="bar-row"><div class="bar-label" title="${{k}}">${{k}}</div><div class="track"><div class="bar" style="width:${{(v/max*100).toFixed(1)}}%"></div></div><div>${{v}}</div></div>`).join('') || '<div class="empty">No profile data.</div>';
}}
function legend(classes) {{
 return `<div class="legend">${{classes.map(c=>`<span><i class="swatch" style="background:${{COLORS[c]||'#999'}}"></i>${{labelOf(c)}}</span>`).join('')}}</div>`;
}}
function svgBarChart(rows, opts={{}}) {{
 const width = 760, barH = opts.barH || 24, gap = opts.gap || 9, left = opts.left || 160, right = 72;
 const height = Math.max(80, rows.length * (barH + gap) + 22);
 const max = Math.max(1, ...rows.map(r=>r.value || 0));
 const parts = rows.map((r,i) => {{
  const y = 8 + i * (barH + gap);
  const w = Math.max(2, (width-left-right) * (r.value || 0) / max);
  const color = r.color || COLORS[r.class] || '#739a83';
  return `<text x="0" y="${{y+barH*.68}}" font-size="12" fill="#405048">${{r.label}}</text><rect x="${{left}}" y="${{y}}" width="${{w.toFixed(1)}}" height="${{barH}}" rx="5" fill="${{color}}"></rect><text x="${{left+w+8}}" y="${{y+barH*.68}}" font-size="12" fill="#304039">${{fmt(r.value)}}</text>`;
 }}).join('');
 return `<div class="chart"><svg viewBox="0 0 ${{width}} ${{height}}" role="img">${{parts}}</svg></div>`;
}}
function stackedTickChart(run) {{
 const ticks = Array.from(new Set((run.by_tick_class||[]).map(r=>r.tick))).sort((a,b)=>a-b);
 const classes = keyClasses.filter(c => (run.by_tick_class||[]).some(r => r.class === c && r.count > 0));
 if (!ticks.length || !classes.length) return '<div class="empty">No exposure timeline yet.</div>';
 const byTick = new Map(ticks.map(t => [t, Object.fromEntries(classes.map(c => [c,0]))]));
 for (const r of run.by_tick_class || []) if (byTick.has(r.tick) && classes.includes(r.class)) byTick.get(r.tick)[r.class] += r.count || 0;
 const width = 820, height = 310, left = 46, right = 12, top = 18, bottom = 36;
 const innerW = width-left-right, innerH = height-top-bottom;
 const maxTotal = Math.max(1, ...ticks.map(t => Object.values(byTick.get(t)).reduce((a,b)=>a+b,0)));
 const bw = innerW / ticks.length * .72;
 const gap = innerW / ticks.length;
 let shapes = '';
 for (const [i,t] of ticks.entries()) {{
  let yBase = top + innerH;
  const x = left + i * gap + (gap-bw)/2;
  for (const c of classes) {{
   const v = byTick.get(t)[c] || 0;
   const h = innerH * v / maxTotal;
   yBase -= h;
   if (h > 0) shapes += `<rect x="${{x.toFixed(1)}}" y="${{yBase.toFixed(1)}}" width="${{bw.toFixed(1)}}" height="${{Math.max(1,h).toFixed(1)}}" fill="${{COLORS[c]||'#999'}}"><title>tick ${{t}} · ${{labelOf(c)}} · ${{v}}</title></rect>`;
  }}
  shapes += `<text x="${{(x+bw/2).toFixed(1)}}" y="${{height-12}}" text-anchor="middle" font-size="11" fill="#68746f">${{t}}</text>`;
 }}
 const guides = [0,.25,.5,.75,1].map(p => {{
  const y = top + innerH - innerH*p;
  return `<line x1="${{left}}" x2="${{width-right}}" y1="${{y}}" y2="${{y}}" stroke="#edf1ee"></line><text x="6" y="${{y+4}}" font-size="10" fill="#87928d">${{Math.round(maxTotal*p)}}</text>`;
 }}).join('');
 return `<div class="chart"><svg viewBox="0 0 ${{width}} ${{height}}" role="img">${{guides}}${{shapes}}<text x="${{left}}" y="12" font-size="11" fill="#68746f">exposures per tick</text></svg></div>${{legend(classes)}}`;
}}
function propagationCards(run) {{
 const rows = classRows(run).filter(r => r.exposures > 0).slice(0,6);
 return `<div class="class-cards">${{rows.map(r=>`<div class="class-card"><div class="name">${{r.class}}</div><div class="big">${{fmt(r.exposures)}}</div><div class="meta">触达 ${{fmt(r.exposed_accounts)}} · 打开 ${{fmt(r.views)}} · 评论 ${{fmt(r.comments)}}</div></div>`).join('')}}</div>`;
}}
function exposureFunnel(run) {{
 const rows = classRows(run).filter(r => r.exposures > 0).slice(0,8).map(r => ({{
  label: r.class, value: r.exposures, class: Object.entries(DATA.class_labels || {{}}).find(([,v]) => v === r.class)?.[0] || 'other'
 }}));
 return svgBarChart(rows, {{left:150, barH:22}});
}}
function topPostsChart(run) {{
 const rows = (run.top_posts || []).slice(0,10).map((p,i) => ({{
  label: (p.post_id || '').replace('post_su7_','').replace('background_','bg_'),
  value: p.exposures || 0,
  class: p.class
 }}));
 return svgBarChart(rows, {{left:190, barH:19}});
}}
function heatmap(rows) {{
 if(!rows.length) return '<div class="empty">No group exposure data.</div>';
 const classes = keyClasses.filter(c => rows.some(r => r.class === c && r.count > 0));
 const groups = Array.from(new Set(rows.map(r => r.group))).slice(0,8);
 const max = Math.max(1, ...rows.map(r => r.count || 0));
 const by = new Map(rows.map(r => [`${{r.group}}|${{r.class}}`, r.count || 0]));
 const head = `<div class="heat-row"><div></div>${{classes.map(c=>`<div class="heat-head" title="${{labelOf(c)}}">${{labelOf(c).slice(0,4)}}</div>`).join('')}}</div>`;
 const body = groups.map(g => `<div class="heat-row"><div class="heat-label" title="${{g}}">${{g}}</div>${{classes.map(c=>{{
  const v = by.get(`${{g}}|${{c}}`) || 0;
  const a = .12 + .78 * v / max;
  return `<div class="heat-cell" style="background:rgba(45,90,75,${{a.toFixed(2)}})">${{v || ''}}</div>`;
 }}).join('')}}</div>`).join('');
 return `<div class="heatmap">${{head}}${{body}}</div>`;
}}
function classRows(run) {{
 return Object.entries(run.metrics||{{}}).map(([cls,m])=>({{class: labelOf(cls), posts:m.posts||0, exposures:m.exposures||0, exposed_accounts:m.exposed_accounts||0, views:m.views||0, likes:m.likes||0, comments:m.comments||0, reposts:m.reposts||0}})).sort((a,b)=>b.exposures-a.exposures);
}}
function timeline() {{
 const posts = [...(DATA.seed_posts||[])].sort((a,b)=>(a.tick||0)-(b.tick||0));
 return `<div class="timeline">${{posts.map(p=>`<div class="stage"><div class="tick">tick ${{p.tick||0}}</div><div class="cls">${{labelOf((p.tags||[])[0]||'other')}}</div><div class="text">${{(p.text||'').slice(0,92)}}</div><div>${{(p.tags||[]).slice(0,4).map(t=>`<span class="tag">${{t}}</span>`).join('')}}</div></div>`).join('')}}</div>`;
}}
function runSummary(run) {{
 return [
  kpi(DATA.profiles_count || 0, 'Generated agents', '参与舆情环境的模拟用户'),
  kpi(metric(run,'exposures'), 'Total exposures', '推荐流产生的信息触达'),
  kpi(metric(run,'views'), 'Post opens', '用户主动打开帖子'),
  kpi(metric(run,'comments') + metric(run,'reposts'), 'Comments + reposts', '显性表达与二次传播'),
 ].join('');
}}
function exposureByTick(run) {{
 const byTick = {{}};
 for (const r of run.by_tick_class || []) {{
  byTick[r.tick] = byTick[r.tick] || {{}};
  byTick[r.tick][labelOf(r.class)] = (byTick[r.tick][labelOf(r.class)]||0) + r.count;
 }}
 const rows = Object.entries(byTick).map(([tick,vals])=>({{tick, ...vals}}));
 const classes = Array.from(new Set(rows.flatMap(r=>Object.keys(r).filter(k=>k!=='tick'))));
 return table(rows, [{{key:'tick',label:'tick'}}, ...classes.map(c=>({{key:c,label:c}}))]);
}}
function render() {{
 const run = (DATA.runs || [])[0] || {{metrics:{{}}, has_db:false}};
 document.getElementById('subtitle').textContent = `${{DATA.scenario || 'social_event'}} · strategy=${{DATA.strategy || 'n/a'}} · run=${{run.label || 'seed only'}} · ${{run.has_db ? 'social DB loaded' : 'seed/profile preview only'}}`;
 const classRowsData = classRows(run);
 const app = [];
 app.push(`<div class="grid">${{runSummary(run)}}</div>`);
 app.push(`<div class="grid">${{panel('曝光趋势：不同信息类型如何进入推荐流', stackedTickChart(run), 'span-8')}}${{panel('传播结构概览', propagationCards(run), 'span-4')}}</div>`);
 app.push(`<div class="grid">${{panel('信息类型传播漏斗', exposureFunnel(run), 'span-7')}}${{panel('人群画像分布', '<b>平台倾向</b>'+bars(DATA.profile_distributions.platform_archetype,8)+'<br><b>媒体偏好</b>'+bars(DATA.profile_distributions.media_style,8), 'span-5')}}</div>`);
 app.push(`<div class="grid">${{panel('事件阶段时间线', timeline(), 'span-12')}}</div>`);
app.push(`<div class="grid">${{panel('信息类型明细表', table(classRowsData, [
  {{key:'class',label:'信息类型'}}, {{key:'posts',label:'帖子'}}, {{key:'exposures',label:'曝光'}}, {{key:'exposed_accounts',label:'触达账号'}}, {{key:'views',label:'打开'}}, {{key:'likes',label:'点赞'}}, {{key:'comments',label:'评论'}}, {{key:'reposts',label:'转发'}}
 ]), 'span-8')}}${{panel('关键帖子曝光排行', topPostsChart(run), 'span-4')}}</div>`);
 const group = ((run.by_group_class||{{}}).media_style||[]).sort((a,b)=>b.count-a.count).slice(0,24);
 app.push(`<div class="grid">${{panel('媒体偏好 x 信息类型触达热力图', heatmap(group), 'span-7')}}${{panel('系统状态与下一步', `<div class="insight-grid"><div class="insight"><b>${{fmt(metric(run,'exposures'))}}</b><span>真实平台曝光记录</span></div><div class="insight"><b>${{fmt(metric(run,'comments'))}}</b><span>评论行为</span></div><div class="insight"><b>${{fmt(metric(run,'likes')+metric(run,'reposts'))}}</b><span>点赞与转发</span></div></div><br><div class="note">${{run.has_db ? '已读取 social.sqlite3，可展示真实曝光、打开和互动。' : '当前未发现 social.sqlite3，dashboard 展示 seed/profiles 预览。跑一次配置后刷新即可看到传播指标。'}}</div><br><div class="note"><span class="warn">建议补充：</span>多策略 run 对比、评论文本立场分类、agent drilldown、平台干预权重。</div>`, 'span-5')}}</div>`);
 app.push(`<div class="grid">${{panel('按 tick 的曝光数据表', exposureByTick(run), 'span-12')}}</div>`);
 document.getElementById('app').innerHTML = app.join('');
}}
render();
</script>
</body>
</html>"""


def main() -> None:
	parser = argparse.ArgumentParser(description="Generate a static HTML dashboard for KERN social-event simulations.")
	parser.add_argument("--run-dir", action="append", default=[], help="Run directory containing social.sqlite3. Can be repeated.")
	parser.add_argument("--seed-json", default="", help="Social seed JSON path.")
	parser.add_argument("--profiles-json", default="", help="Profiles JSON path.")
	parser.add_argument("--class-map-json", default="", help="Optional class map JSON.")
	parser.add_argument("--out-html", default="checkpoints/social_event_dashboard.html", help="Output dashboard HTML.")
	parser.add_argument("--out-json", default="", help="Optional output summary JSON.")
	args = parser.parse_args()

	base = Path.cwd()
	run_dirs = [Path(x).resolve() for x in list(args.run_dir or []) if str(x).strip()]
	seed_path = _resolve(base, args.seed_json)
	profiles_path = _resolve(base, args.profiles_json)
	class_map = DEFAULT_CLASSES
	class_map_path = _resolve(base, args.class_map_json)
	if class_map_path is not None and class_map_path.exists():
		raw = _load_json(class_map_path)
		if raw:
			class_map = {str(k): [str(x) for x in list(v or [])] for k, v in raw.items()}
	if not run_dirs:
		run_dirs = [Path("checkpoints/seed_preview").resolve()]
	data = build_data(run_dirs, seed_path, profiles_path, class_map)
	out_html = Path(args.out_html)
	if not out_html.is_absolute():
		out_html = base / out_html
	out_html.parent.mkdir(parents=True, exist_ok=True)
	out_html.write_text(_html(data), encoding="utf-8")
	if args.out_json:
		out_json = Path(args.out_json)
		if not out_json.is_absolute():
			out_json = base / out_json
		out_json.parent.mkdir(parents=True, exist_ok=True)
		out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"wrote dashboard: {out_html}")


if __name__ == "__main__":
	main()
