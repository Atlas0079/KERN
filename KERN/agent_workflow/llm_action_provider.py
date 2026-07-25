from __future__ import annotations

import json
import re
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..execution_errors import KernFailure
from ..failure_report import FailureEvidence
from ..log_manager import get_logger
from ..llm.openai_compat_client import DualModelLLM, OpenAICompatClient, LLMRequestError
from ..llm.gemini_client import GeminiClient
from .dialogue import DialogueFrame, Pass, Speak
from .observer import build_agent_perception
from .trace import LLMTraceRecorder
from .workflow_contract import (
	build_action_plan_decision,
	build_end_turn_decision,
)


class GroundingUngroundable(Exception):
	def __init__(self, reason: str) -> None:
		self.reason = str(reason or "").strip() or "Grounder reported the planner intent could not be mapped to available actions."
		super().__init__(self.reason)


def _repo_root() -> Path:
	# KERN/agent_workflow/llm_action_provider.py -> repo root
	return Path(__file__).resolve().parents[2]


def _read_text(path: Path) -> str:
	return path.read_text(encoding="utf-8")


def _fill_template(template: str, mapping: dict[str, Any]) -> str:
	out = str(template)
	for k, v in (mapping or {}).items():
		out = out.replace(f"{{{{{k}}}}}", str(v))
	return out


def _entities_table(entities: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for e in list(entities or []):
		if not isinstance(e, dict):
			continue
		eid = str(e.get("id", "") or "")
		name = str(e.get("name", "") or "")
		tags = e.get("tags", []) or []
		statuses = [str(x) for x in list(e.get("statuses", []) or [])]
		desc = str(e.get("description", "") or "").strip()
		contained_in = str(e.get("contained_in", "") or "")
		contained_in_slot = str(e.get("contained_in_slot", "") or "")
		is_top_level = bool(e.get("is_top_level", False))
		where = "ground" if is_top_level else (f"in:{contained_in}/{contained_in_slot}" if contained_in else "unknown")
		tasks = e.get("tasks", []) or []
		task_text = ""
		if isinstance(tasks, list) and tasks:
			summaries: list[str] = []
			for t in tasks:
				if not isinstance(t, dict):
					continue
				ttype = str(t.get("task_type", "") or "")
				status = str(t.get("task_status", "") or "")
				prog = float(t.get("progress", 0.0) or 0.0)
				req = float(t.get("required_progress", 0.0) or 0.0)
				assigned = t.get("assigned_agent_ids", []) or []
				assigned_cnt = len(list(assigned)) if isinstance(assigned, list) else 0
				avail = bool(t.get("is_available", False))
				required_tool = str(t.get("required_item_tag", "") or "").strip()
				done_status = str(t.get("done_status_id", "") or "").strip()
				extras: list[str] = []
				if required_tool:
					extras.append(f"requires:{required_tool}")
				if done_status:
					extras.append(f"done_when:{done_status}")
				extra_text = f",{','.join(extras)}" if extras else ""
				summaries.append(
					f"{ttype}({prog:g}/{req:g},{status or 'Unknown'},{'available' if avail else f'assigned:{assigned_cnt}'}{extra_text})"
				)
			if summaries:
				task_text = f", tasks: [{'; '.join(summaries)}]"
		desc_text = f", description: {desc}" if desc else ""
		lines.append(f"- id: {eid}, name: {name}, tags: {list(tags)}, statuses: {list(statuses)}, where: {where}{desc_text}{task_text}")
	return "\n".join(lines) if lines else "(No visible entities)"


def _entities_table_planner(entities: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for e in list(entities or []):
		if not isinstance(e, dict):
			continue
		name = str(e.get("name", "") or "")
		tags = [str(x) for x in list(e.get("tags", []) or [])]
		statuses = [str(x) for x in list(e.get("statuses", []) or [])]
		desc = str(e.get("description", "") or "").strip()
		contained_in = str(e.get("contained_in", "") or "")
		is_top_level = bool(e.get("is_top_level", False))
		where = "地面可见" if is_top_level else ("容器内可见" if contained_in else "位置未知")
		tasks = e.get("tasks", []) or []
		task_text = ""
		if isinstance(tasks, list) and tasks:
			summaries: list[str] = []
			for t in tasks:
				if not isinstance(t, dict):
					continue
				ttype = str(t.get("task_type", "") or "")
				status = str(t.get("task_status", "") or "")
				prog = float(t.get("progress", 0.0) or 0.0)
				req = float(t.get("required_progress", 0.0) or 0.0)
				assigned = t.get("assigned_agent_ids", []) or []
				assigned_cnt = len(list(assigned)) if isinstance(assigned, list) else 0
				avail = bool(t.get("is_available", False))
				required_tool = str(t.get("required_item_tag", "") or "").strip()
				extra = f"，需工具:{required_tool}" if required_tool else ""
				summaries.append(f"{ttype}({prog:g}/{req:g},{status or 'Unknown'},{'可接取' if avail else f'已分配:{assigned_cnt}'}{extra})")
			if summaries:
				task_text = f"，任务: {'; '.join(summaries)}"
		desc_text = f"，描述:{desc}" if desc else ""
		lines.append(f"- {name}（tags:{tags}，状态:{statuses if statuses else '无'}，{where}{desc_text}{task_text}）")
	return "\n".join(lines) if lines else "(No visible entities)"


def _inventory_table(inventory: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(inventory or []):
		if not isinstance(item, dict):
			continue
		eid = str(item.get("id", "") or "")
		name = str(item.get("name", "") or "")
		tags = item.get("tags", []) or []
		slot = str(item.get("slot", "") or "")
		statuses = item.get("statuses", []) or []
		lines.append(f"- id: {eid}, name: {name}, tags: {list(tags)}, statuses: {list(statuses)}, slot: {slot}")
	return "\n".join(lines) if lines else "(Empty)"


def _inventory_table_planner(inventory: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(inventory or []):
		if not isinstance(item, dict):
			continue
		name = str(item.get("name", "") or "")
		tags = [str(x) for x in list(item.get("tags", []) or [])]
		statuses = [str(x) for x in list(item.get("statuses", []) or [])]
		lines.append(f"- {name}（tags:{tags}，状态:{statuses if statuses else '无'}）")
	return "\n".join(lines) if lines else "(Empty)"


def _reachable_locations_text(reachable_locations: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(reachable_locations or []):
		if not isinstance(item, dict):
			continue
		to_id = str(item.get("to_location_id", "") or "")
		to_name = str(item.get("to_location_name", "") or "")
		distance = float(item.get("distance", 0.0) or 0.0)
		lines.append(f"- {to_id} / {to_name} (distance={distance:g})")
	return "\n".join(lines) if lines else "(No reachable locations)"


def _reachable_locations_text_planner(reachable_locations: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(reachable_locations or []):
		if not isinstance(item, dict):
			continue
		to_name = str(item.get("to_location_name", "") or "")
		distance = float(item.get("distance", 0.0) or 0.0)
		lines.append(f"- {to_name} (distance={distance:g})")
	return "\n".join(lines) if lines else "(No reachable locations)"


def _map_topology_text(map_topology: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for loc in list(map_topology or []):
		if not isinstance(loc, dict):
			continue
		loc_id = str(loc.get("location_id", "") or "")
		loc_name = str(loc.get("location_name", "") or "")
		neighbors = loc.get("neighbors", []) or []
		neighbor_texts: list[str] = []
		for n in list(neighbors):
			if not isinstance(n, dict):
				continue
			to_id = str(n.get("to_location_id", "") or "")
			to_name = str(n.get("to_location_name", "") or "")
			distance = float(n.get("distance", 0.0) or 0.0)
			neighbor_texts.append(f"{to_id}/{to_name}(distance={distance:g})")
		neighbor_joined = ", ".join(neighbor_texts) if neighbor_texts else "(none)"
		lines.append(f"- {loc_id} / {loc_name} -> {neighbor_joined}")
	return "\n".join(lines) if lines else "(No map topology)"


def _participants_table(participants: list[str]) -> str:
	lines = [f"- {str(x)}" for x in list(participants or []) if str(x)]
	return "\n".join(lines) if lines else "(No participants)"


def _conversation_transcript_text(transcript: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(transcript or []):
		if not isinstance(item, dict):
			continue
		utterance_index = int(item.get("utterance_index", 0) or 0)
		speaker_name = str(item.get("speaker_name", "") or item.get("speaker_id", "") or "unknown")
		text = str(item.get("text", "") or "").strip()
		pass_turn = bool(item.get("pass", False))
		body = "PASS" if pass_turn or not text else text
		lines.append(f"- [{utterance_index}] {speaker_name}: {body}")
	return "\n".join(lines) if lines else "(No transcript yet)"


def _interrupt_preset_summaries_text(summaries: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(summaries or []):
		if not isinstance(item, dict):
			continue
		pid = str(item.get("preset_id", "") or "")
		desc = str(item.get("description", "") or "")
		if pid and desc:
			lines.append(f"- {pid}: {desc}")
		elif pid:
			lines.append(f"- {pid}")
	return "\n".join(lines) if lines else ""


def _task_summary_from_perception(perception: dict[str, Any]) -> str:
	task_id = str((perception or {}).get("current_task_id", "") or "")
	if not task_id:
		return "无当前任务"
	task_type = str((perception or {}).get("current_task_type", "") or "")
	task_status = str((perception or {}).get("current_task_status", "") or "")
	progress = float((perception or {}).get("current_task_progress", 0.0) or 0.0)
	required_progress = float((perception or {}).get("current_task_required_progress", 0.0) or 0.0)
	return f"{task_id} / {task_type or 'Unknown'} / {task_status or 'Unknown'} / {progress:g}/{required_progress:g}"


def _fmt_vital(value: Any) -> str:
	if value is None:
		return "?"
	try:
		return f"{float(value):.1f}"
	except Exception:
		return "?"


def _vitals_text(vitals: dict[str, Any]) -> str:
	v = dict(vitals or {}) if isinstance(vitals, dict) else {}
	if not v:
		return "未知"
	parts = [
		f"hp {_fmt_vital(v.get('hp'))}/{_fmt_vital(v.get('max_hp'))}",
		f"energy {_fmt_vital(v.get('energy'))}/{_fmt_vital(v.get('max_energy'))}",
		f"nutrition {_fmt_vital(v.get('nutrition'))}/{_fmt_vital(v.get('max_nutrition'))}",
	]
	if "stress" in v or "max_stress" in v:
		parts.append(f"stress {_fmt_vital(v.get('stress'))}/{_fmt_vital(v.get('max_stress'))}")
	return ", ".join(parts)


def _location_light_text(location: dict[str, Any], blocked_by_darkness: bool) -> str:
	loc = dict(location or {}) if isinstance(location, dict) else {}
	try:
		light_level = int(loc.get("light_level", 2))
	except Exception:
		light_level = 2
	if bool(blocked_by_darkness):
		return f"light_level={light_level}，当前地点过暗，无法被动感知实体。"
	return f"light_level={light_level}"


def _with_mode_context(perception: dict[str, Any], mode: str, mode_context: dict[str, Any] | None = None) -> dict[str, Any]:
	out = dict(perception or {})
	out["mode"] = str(mode or "").strip()
	out["mode_context"] = dict(mode_context or {})
	return out


def _build_agent_context(perception: dict[str, Any], self_id: str) -> dict[str, Any]:
	p = dict(perception or {})
	loc = p.get("location", {}) or {}
	mode_context = p.get("mode_context", {}) or {}
	return {
		"self_id": str(self_id or p.get("self_id", "") or ""),
		"agent_name": str(p.get("agent_name", "") or self_id),
		"personality_summary": str(p.get("personality_summary", "") or ""),
		"common_knowledge_summary": str(p.get("common_knowledge_summary", "") or ""),
		"short_term_memory_text": str(p.get("short_term_memory_text", "") or ""),
		"short_term_memory_items": list(p.get("short_term_memory_items", []) or []),
		"recent_interactions": [dict(x) for x in list(p.get("recent_interactions", []) or []) if isinstance(x, dict)],
		"recent_interactions_text": str(p.get("recent_interactions_text", "") or ""),
		"mid_term_summary": str(p.get("mid_term_summary", "") or ""),
		"vitals": dict(p.get("vitals", {}) or {}) if isinstance(p.get("vitals", {}), dict) else {},
		"vitals_text": _vitals_text(dict(p.get("vitals", {}) or {}) if isinstance(p.get("vitals", {}), dict) else {}),
		"tick": p.get("tick", None),
		"tick_str": str(p.get("tick", "") or ""),
		"location": dict(loc) if isinstance(loc, dict) else {},
		"location_light_text": _location_light_text(loc if isinstance(loc, dict) else {}, bool(p.get("perception_blocked_by_darkness", False))),
		"perception_blocked_by_darkness": bool(p.get("perception_blocked_by_darkness", False)),
		"map_topology": list(p.get("map_topology", []) or []),
		"reachable_locations": list(p.get("reachable_locations", []) or []),
		"visible_entities": list(p.get("entities", []) or []),
		"inventory": list(p.get("inventory", []) or []),
		"can_start_conversation_here": bool(p.get("can_start_conversation_here", True)),
		"current_task_id": str(p.get("current_task_id", "") or ""),
		"current_task_type": str(p.get("current_task_type", "") or ""),
		"current_task_status": str(p.get("current_task_status", "") or ""),
		"current_task_progress": float(p.get("current_task_progress", 0.0) or 0.0),
		"current_task_required_progress": float(p.get("current_task_required_progress", 0.0) or 0.0),
		"current_task_summary": _task_summary_from_perception(p),
		"active_interrupt_preset_id": str(p.get("active_interrupt_preset_id", "") or ""),
		"available_interrupt_presets": list(p.get("available_interrupt_presets", []) or []),
		"interrupt_preset_summaries": list(p.get("interrupt_preset_summaries", []) or []),
		"interrupt_preset_summaries_text": _interrupt_preset_summaries_text(list(p.get("interrupt_preset_summaries", []) or [])),
		"mode": str(p.get("mode", "") or ""),
		"mode_context": dict(mode_context) if isinstance(mode_context, dict) else {},
	}


def _build_available_verbs(
	recipe_db: dict[str, Any],
	visible_entities: list[dict[str, Any]],
	inventory: list[dict[str, Any]],
	reachable_locations: list[dict[str, Any]],
	can_start_conversation_here: bool,
) -> tuple[str, str, set[str]]:
	"""
	Return:
	- available_verbs_list: verb list for grounder (text)
	- available_verbs_with_duration: verb + instant/duration for planner (text)
	- allowed_verbs_set: for validation
	"""

	def _is_duration_process(process_data: dict[str, Any]) -> bool:
		process = dict(process_data or {}) if isinstance(process_data, dict) else {}
		duration = process.get("duration", {}) or {}
		if isinstance(duration, dict) and duration:
			return True
		required_progress = float(process.get("required_progress", 0) or 0)
		return required_progress != 0

	# Visible tag set (n)
	visible_tags: set[str] = set()
	for e in list(visible_entities or []):
		tags = (e or {}).get("tags", []) or []
		for t in list(tags):
			visible_tags.add(str(t))

	verbs: dict[str, str] = {}  # verb -> "instant"/"duration"
	def _has_available_task_host() -> bool:
		for ent in list(visible_entities or []):
			if not isinstance(ent, dict):
				continue
			tasks = ent.get("tasks", []) or []
			if not isinstance(tasks, list):
				continue
			for task in tasks:
				if not isinstance(task, dict):
					continue
				if bool(task.get("is_available", False)):
					return True
		return False
	def _inv_has_tag(tag: str) -> bool:
		for it in list(inventory or []):
			if not isinstance(it, dict):
				continue
			tags = [str(x) for x in list(it.get("tags", []) or [])]
			if str(tag) in tags:
				return True
		return False
	def _inv_has_status(tag: str, status_id: str) -> bool:
		for it in list(inventory or []):
			if not isinstance(it, dict):
				continue
			tags = [str(x) for x in list(it.get("tags", []) or [])]
			if str(tag) not in tags:
				continue
			statuses = [str(x) for x in list(it.get("statuses", []) or [])]
			if str(status_id) in statuses:
				return True
		return False
	for _rid, recipe in (recipe_db or {}).items():
		if not isinstance(recipe, dict):
			continue
		verb = str(recipe.get("verb", "") or "").strip()
		if not verb:
			continue
		req_tags = list(recipe.get("target_tags", []) or [])
		tag_match_mode = str(recipe.get("target_tags_match", "all") or "all").strip().lower()
		ok = True
		if req_tags:
			if tag_match_mode == "any":
				ok = any(str(tag) in visible_tags for tag in req_tags)
			else:
				for tag in req_tags:
					if str(tag) not in visible_tags:
						ok = False
						break
		if not ok:
			continue
		if verb == "Travel" and not reachable_locations:
			continue
		if verb == "Talk" and not bool(can_start_conversation_here):
			continue
		if verb == "AcceptTask" and not _has_available_task_host():
			continue
		if verb == "ShootRevolver" and not _inv_has_status("revolver", "revolver_loaded"):
			continue
		if verb == "ReloadRevolver" and (not _inv_has_status("revolver", "revolver_unloaded") or not _inv_has_tag("bullet")):
			continue
		if verb == "ShootShockPistol" and not _inv_has_status("shock_pistol", "shock_charged"):
			continue
		process = recipe.get("process", {}) or {}
		verbs[verb] = "duration" if _is_duration_process(process) else "instant"

	allowed = set(verbs.keys())

	# For grounder: Only verb names (m)
	available_verbs_list = "\n".join([f"- {v}" for v in sorted(allowed)]) if allowed else "(No available verbs)"

	# For planner: verb + instant/duration (m)
	with_duration_lines = [f"- {v}: {verbs[v]}" for v in sorted(allowed)]
	available_verbs_with_duration = "\n".join(with_duration_lines) if with_duration_lines else "(No available verbs)"

	return (available_verbs_list, available_verbs_with_duration, allowed)


def _build_recipe_hints(recipe_db: dict[str, Any], allowed_verbs: set[str]) -> tuple[str, str]:
	planner_lines: list[str] = []
	grounder_lines: list[str] = []
	seen_planner: set[str] = set()
	seen_grounder: set[str] = set()
	for _rid, recipe in (recipe_db or {}).items():
		if not isinstance(recipe, dict):
			continue
		verb = str(recipe.get("verb", "") or "").strip()
		if not verb or verb not in allowed_verbs:
			continue
		planner_hint = str(recipe.get("planner_hint", "") or "").strip()
		grounder_hint = str(recipe.get("grounder_hint", "") or "").strip()
		if planner_hint:
			line = f"- {verb}: {planner_hint}"
			if line not in seen_planner:
				seen_planner.add(line)
				planner_lines.append(line)
		if grounder_hint:
			line = f"- {verb}: {grounder_hint}"
			if line not in seen_grounder:
				seen_grounder.add(line)
				grounder_lines.append(line)
	return ("\n".join(planner_lines), "\n".join(grounder_lines))


@dataclass
class LLMActionProvider:
	"""
	Two-Layer LLM Action Generator:
	- Planner: Output high-level natural language intent
	- Grounder: Output multi-step action JSON array

	Explanation:
	- Planner receives perception and memory derived from Agent-visible interaction records.
	- The machine-readable event log is not part of the Agent workflow view.
	"""

	llm: DualModelLLM
	planner_template_path: Path = _repo_root() / "docs" / "scenario_authoring" / "LLMContext_Planner.md"
	grounder_template_path: Path = _repo_root() / "docs" / "scenario_authoring" / "LLMContext_Grounder.md"
	dialogue_template_path: Path = _repo_root() / "docs" / "scenario_authoring" / "LLMContext_Dialogue.md"
	debug: bool = False
	focus_agent_id: str = ""
	focus_log_prompts: bool = False
	focus_log_perception: bool = True
	llm_debug_view: str = ""
	failure_evidence: FailureEvidence = field(default_factory=FailureEvidence)
	trace_recorder: LLMTraceRecorder | None = None

	def _new_failure_context(
		self,
		*,
		context_type: str,
		actor_id: str,
		tick: int,
		location_id: str,
		perception: dict[str, Any],
		reason: str = "",
	) -> dict[str, Any] | None:
		recorder = self.failure_evidence
		if recorder is None or not recorder.enabled:
			return None
		client = getattr(self.llm, "client", None)
		return {
			"trace_id": uuid4().hex,
			"context_type": str(context_type or "llm_decision"),
			"actor_id": str(actor_id or ""),
			"tick": int(tick or 0),
			"location_id": str(location_id or ""),
			"reason": str(reason or ""),
			"provider": {
				"type": str(type(client).__name__) if client is not None else str(type(self.llm).__name__),
				"planner_model": str(getattr(self.llm, "planner_model", "") or ""),
				"grounder_model": str(getattr(self.llm, "grounder_model", "") or ""),
				"base_url": str(getattr(client, "base_url", "") or ""),
				"api_prefix": str(getattr(client, "api_prefix", "") or ""),
			},
			"perception": dict(perception or {}),
			"attempts": [],
		}

	def _persist_trace(self, context: dict[str, Any] | None, status: str) -> str:
		if not isinstance(context, dict):
			return ""
		context["status"] = str(status or "")
		trace_id = str(context.get("trace_id", "") or "")
		if self.trace_recorder is not None:
			self.trace_recorder.record(context)
		return trace_id

	def _failure_request(self, *, model: str, temperature: float, messages: list[dict[str, Any]]) -> dict[str, Any]:
		return {
			"model": str(model or ""),
			"temperature": float(temperature),
			"max_tokens": None,
			"response_format": None,
			"messages": [dict(item) for item in messages],
			"request_extra": dict(getattr(self.llm, "request_extra", {}) or {}),
		}

	def _record_failure_evidence(
		self,
		context: dict[str, Any] | None,
		*,
		kind: str,
		stage: str,
		summary: str,
		details: dict[str, Any] | None = None,
	) -> None:
		recorder = self.failure_evidence
		if recorder is None or not recorder.enabled:
			return
		ctx = dict(context or {})
		recorder.record_failure(
			kind=kind,
			stage=stage,
			summary=summary,
			tick=int(ctx.get("tick", 0) or 0),
			actor_id=str(ctx.get("actor_id", "") or ""),
			location_id=str(ctx.get("location_id", "") or ""),
			details=dict(details or {}),
			context=ctx,
		)

	# System Prompt Definition
	PLANNER_SYSTEM_PROMPT = """
你是沙盒世界中的一名角色/智能体。你需要基于用户提供的上下文决定下一步做什么。

**强约束：**
- 你只能输出“高层自然语言意图/下一目标”。
- 地点是离散节点。如果你的意图涉及跨地点移动，执行层会把它转换为耗时任务；一旦进入任务，你会暂时让出行动权。
- 你不是全知的：只能依赖“当前观测”和“最近交互叙事”进行推理。
- 不要输出备选策略/分支计划/多方案对比。
- 不要在意图里指定具体 tick 时长（例如休息/睡觉/移动会由系统按配方与路径自动决定耗时）。
- 你必须遵循 Action 串原则：你的意图必须能被“当前可用动词列表”落地，不能假设不可用动词或不可见目标。
- 你可以保持语义层面的灵活性，但不能违反可执行性边界；若某动作当前不可执行，你应改写成可执行替代意图。
- 当可见实体任务状态显示“已分配/不可接取”时，不得输出“接取该任务”相关意图。

**你必须输出：**
- 严格输出以下两段（按顺序）：
THOUGHT: <1-3句，简短思考摘要，不得包含JSON>
INTENT: <1-3句，给Grounder使用的实际意图，必须可执行>
"""

	GROUNDER_SYSTEM_PROMPT = """
你是“动作落地器（Action Grounder）”。你的任务是把 Planner 的自然语言意图翻译成具体的 Action JSON 序列。

**输入：**
- Planner 意图：高层自然语言描述。
- 可见实体列表：你在当前位置真实可操作的实体。
- 背包列表：你携带的物品。
- 可用动词列表：当前允许使用的动词。
- Recipe Grounder Hints：特定动词的额外参数约束（如果提供）。

**输出约束（关键）：**
1. 如果 Planner 意图可以落地，必须输出一个 JSON 数组，数组元素是 Action 对象。
2. Action 对象格式为：`{"verb": "verb", "parameters": {}}`，并且在需要时可以包含 `"target_id"`。
3. 只能使用“可用动词列表”中的动词。
4. 对于非 meta 动词，通常需要提供 `target_id`，且必须来自“可见实体列表”或“背包列表”；但 Talk 是例外（不得提供 target_id）。对于 meta 动词，你不得提供 `target_id`（系统会自动填充为你自己）。
5. 对于耗时动作，它必须是序列中的最后一个动作（因为会触发 Task 并占用行动权）。
6. 不要在 JSON 外层添加任何 Markdown 标签（如 ```json），只输出纯 JSON 字符串。
7. 如果 Planner 意图无法用当前可用动词和可见/背包实体落地，输出 `{"type":"ungroundable","reason":"<具体原因>"}`。reason 必须说明缺少哪个动作、目标或参数约束，不要硬凑不存在的动作。

**动词特定参数规则（重要）：**
- SwitchInterruptPreset（meta）：parameters 必须包含 `{"preset_id": "<available_interrupt_presets 中的一个>"}`，且不得提供 target_id。
- InspectInterruptPresets（meta）：可选参数 `{"preset_id": "<可选>"}`，且不得提供 target_id。
- Travel（non-meta）：target_id 必须是 self id，parameters 必须包含 `{"to_location_id": "<reachable_locations.to_location_id 之一>"}`。
- Talk（non-meta）：不得提供 target_id；parameters 必须包含 `{"text": "<非空开场白>"}`。执行后会触发“当前地点群体对话”，该 text 作为第一轮发言，然后同地点其他角色按轮次继续。
- YieldCurrentTask（non-meta，仅在中断决策阶段可用）：不得提供 target_id；parameters 必须为空对象 `{}`，表示先放下当前任务，再进入常规决策。
- Give（non-meta）：target_id 必须是一个可见 agent 的 id，且 parameters 必须包含 `{"item_id": "<你背包中物品的id>"}`。
- 对于出现在 Recipe Grounder Hints 中的动词，你必须满足对应 hint 约束。
"""


	DIALOGUE_SYSTEM_PROMPT = """
You are in an in-world conversation turn.

Output rules:
1. Output exactly one line.
2. Either output PASS, or a short spoken sentence in character.
3. Do not output JSON.
4. Do not narrate actions.
"""

	def _is_focus_agent(self, self_id: str) -> bool:
		fid = str(self.focus_agent_id or "").strip()
		return bool(fid) and str(self_id or "").strip() == fid

	def _focus_log(self, logger: Any, event: str, self_id: str, context: dict[str, Any]) -> None:
		if not bool(self.focus_log_prompts):
			return
		if not self._is_focus_agent(self_id):
			return
		logger.warn("llm", str(event), context=dict(context or {}))

	def decide(
		self,
		ws_view: Any,
		recipe_db: dict[str, Any] | None,
		actor_id: str,
		reason: str,
		mode_context: dict[str, Any] | None = None,
	) -> dict[str, Any]:
		view_payload = dict(ws_view or {}) if isinstance(ws_view, dict) else {}
		full_ws_view = dict(view_payload.get("full_ws_view", {}) or {}) if isinstance(view_payload.get("full_ws_view", {}), dict) else {}
		if not full_ws_view:
			raise KernFailure(
				"WORKFLOW_INPUT_MISSING_FULL_WS_VIEW",
				"ws_view.full_ws_view is required",
				origin="workflow",
				phase="decision_input",
				context={"actor_id": str(actor_id or "")},
			)
		perception = build_agent_perception(full_ws_view, str(actor_id))
		recipe_db_view = dict(recipe_db or {}) if isinstance(recipe_db, dict) else {}
		mode_ctx = dict(mode_context or view_payload.get("mode_context", {}) or {})
		if mode_ctx:
			perception["mode_context"] = dict(mode_ctx)
		perception["interrupt_reason"] = str(reason or "")
		location = dict(perception.get("location", {}) or {}) if isinstance(perception.get("location", {}), dict) else {}
		failure_context = self._new_failure_context(
			context_type="llm_decision",
			actor_id=str(actor_id),
			tick=int(perception.get("tick", 0) or 0),
			location_id=str(location.get("id", "") or ""),
			perception=perception,
			reason=str(reason or ""),
		)
		try:
			actions = self._decide_actions_from_perception(
				perception,
				recipe_db_view,
				reason,
				str(actor_id),
				failure_context=failure_context,
			)
		except KernFailure:
			self._persist_trace(failure_context, "failed")
			raise
		except GroundingUngroundable as e:
			self._record_failure_evidence(
				failure_context,
				kind="grounding",
				stage="grounder_ungroundable",
				summary=str(e.reason),
				details={"reason": str(e.reason)},
			)
			self._persist_trace(failure_context, "failed")
			raise KernFailure(
				"WORKFLOW_GROUNDING_UNGROUNDED",
				str(e.reason),
				origin="llm",
				phase="grounding",
				context={"actor_id": str(actor_id or ""), "failure_evidence": failure_context or {}},
			) from e
		except ValueError as e:
			self._record_failure_evidence(
				failure_context,
				kind="llm_output",
				stage="grounder_parse",
				summary=str(e),
				details={"error_type": type(e).__name__, "error": str(e), "traceback": traceback.format_exc()},
			)
			self._persist_trace(failure_context, "failed")
			raise KernFailure(
				"WORKFLOW_OUTPUT_PARSE_FAILED",
				str(e),
				origin="llm",
				phase="grounder_parse",
				context={"actor_id": str(actor_id or ""), "failure_evidence": failure_context or {}},
			) from e
		except Exception as e:
			self._record_failure_evidence(
				failure_context,
				kind="infrastructure",
				stage="workflow_decide",
				summary=str(e),
				details={"error_type": type(e).__name__, "error": str(e), "traceback": traceback.format_exc()},
			)
			self._persist_trace(failure_context, "failed")
			raise KernFailure(
				"WORKFLOW_DECIDE_RUNTIME_ERROR",
				str(e),
				origin="llm",
				phase="workflow_decide",
				context={"actor_id": str(actor_id or ""), "failure_evidence": failure_context or {}},
			) from e
		if not list(actions or []):
			trace_id = self._persist_trace(failure_context, "completed")
			return build_end_turn_decision(meta={"provider": "llm_workflow", "reason": "no_actions", "llm_trace_id": trace_id})
		memory_notes: list[dict[str, Any]] = []
		for item in list(actions or []):
			if isinstance(item, dict) and str(item.get("_workflow_note_type", "") or "") == "ungroundable":
				memory_notes.append(self._build_ungroundable_memory_note(str(item.get("reason", "") or ""), full_ws_view))
		action_plan = [
			dict(x)
			for x in list(actions or [])
			if isinstance(x, dict) and str(x.get("_workflow_note_type", "") or "") != "ungroundable"
		]
		if failure_context is not None:
			failure_context["actions"] = [dict(item) for item in action_plan]
		trace_id = self._persist_trace(failure_context, "completed")
		meta = {"provider": "llm_workflow", "llm_trace_id": trace_id}
		if memory_notes:
			meta["memory_notes"] = memory_notes
		if not action_plan:
			return build_end_turn_decision(meta=meta)
		return build_action_plan_decision(
			actions=action_plan,
			meta=meta,
		)

	def _build_ungroundable_memory_note(self, reason: str, full_ws_view: dict[str, Any]) -> dict[str, Any]:
		tick = int((full_ws_view or {}).get("tick", 0) or 0) if isinstance(full_ws_view, dict) else 0
		return {
			"tick": tick,
			"type": "note",
			"topic": "grounding",
			"importance": 0.85,
			"content": f"动作落地失败：{str(reason or '').strip()}",
			"tags": ["grounding", "ungroundable"],
			"source": {"stage": "grounder"},
		}

	def _decide_actions_from_perception(
		self,
		perception: dict[str, Any],
		recipe_db: dict[str, Any],
		reason: str,
		self_id: str | None = None,
		*,
		failure_context: dict[str, Any] | None = None,
	) -> list[dict[str, Any]]:
		logger = get_logger()
		self_id = str(self_id or perception.get("self_id", "") or "")
		perception = dict(perception or {})
		ungroundable_notes: list[str] = []
		for attempt in range(2):
			try:
				return self._decide_actions_once_from_perception(
					perception=perception,
					recipe_db=recipe_db,
					reason=reason,
					self_id=self_id,
					ungroundable_notes=ungroundable_notes,
					failure_context=failure_context,
				)
			except GroundingUngroundable as e:
				note = str(e.reason or "").strip()
				if note:
					ungroundable_notes.append(note)
					mem_items = [dict(x) for x in list(perception.get("short_term_memory_items", []) or []) if isinstance(x, dict)]
					tick = int(perception.get("tick", 0) or 0)
					mem_items.append(
						{
							"tick": tick,
							"type": "note",
							"topic": "grounding",
							"importance": 0.85,
							"content": f"动作落地失败：{note}",
							"tags": ["grounding", "ungroundable"],
						}
					)
					perception["short_term_memory_items"] = mem_items
					existing_text = str(perception.get("short_term_memory_text", "") or "").strip()
					line = f"- [tick {tick}][imp 0.85] [grounding] 动作落地失败：{note}"
					perception["short_term_memory_text"] = f"{existing_text}\n{line}".strip() if existing_text else line
				logger.warn("llm", "grounder_ungroundable", context={"self_id": self_id, "attempt": int(attempt + 1), "reason": note})
				if attempt == 0:
					reason = note
					continue
				raise GroundingUngroundable(note)
		return []

	def _decide_actions_once_from_perception(
		self,
		perception: dict[str, Any],
		recipe_db: dict[str, Any],
		reason: str,
		self_id: str,
		ungroundable_notes: list[str] | None = None,
		failure_context: dict[str, Any] | None = None,
	) -> list[dict[str, Any]]:
		logger = get_logger()
		decision_mode_context = {
			**dict((perception or {}).get("mode_context", {}) or {}),
			"reason": str(reason or ""),
			"interrupt_decision_mode": bool((perception or {}).get("interrupt_decision_mode", False)),
			"interrupt_reason": str((perception or {}).get("interrupt_reason", "") or ""),
		}
		perception = _with_mode_context(perception if isinstance(perception, dict) else {}, "decision", decision_mode_context)
		agent_context = _build_agent_context(perception, self_id)
		visible_entities = list(agent_context.get("visible_entities", []) or [])
		reachable_locations = list(agent_context.get("reachable_locations", []) or [])
		can_start_conversation_here = bool(agent_context.get("can_start_conversation_here", True))
		short_term_memory_text = str(agent_context.get("short_term_memory_text", "") or "")
		recent_interactions_text = str(agent_context.get("recent_interactions_text", "") or "")
		memory_context_text = "\n".join(
			text for text in (recent_interactions_text.strip(), short_term_memory_text.strip()) if text
		)
		short_term_memory_items = list(agent_context.get("short_term_memory_items", []) or [])
		inventory = list(agent_context.get("inventory", []) or [])
		loc = agent_context.get("location", {}) or {}
		loc_id = str((loc or {}).get("id", "") or "")
		loc_name = str((loc or {}).get("name", "") or "")
		tick = agent_context.get("tick", None)
		tick_str = str(agent_context.get("tick_str", "") or "")
		tick_i: int | None = None
		try:
			tick_i = int(tick) if tick is not None else None
		except Exception:
			tick_i = None
		available_verbs_list, available_verbs_with_duration, allowed_verbs = _build_available_verbs(
			recipe_db, visible_entities, inventory, reachable_locations, can_start_conversation_here
		)
		interrupt_mode = bool((perception or {}).get("interrupt_decision_mode", False))
		current_task_id_for_interrupt = str((perception or {}).get("current_task_id", "") or "")
		if interrupt_mode and current_task_id_for_interrupt:
			allowed_verbs = {"YieldCurrentTask"}
			verb_lines = [f"- {v}" for v in sorted(allowed_verbs)]
			available_verbs_list = "\n".join(verb_lines) if verb_lines else "(No available verbs)"
			if "YieldCurrentTask" not in str(available_verbs_with_duration):
				available_verbs_with_duration = (
					f"{available_verbs_with_duration}\n- YieldCurrentTask: instant".strip()
					if available_verbs_with_duration
					else "- YieldCurrentTask: instant"
				)
		planner_recipe_hints, grounder_recipe_hints = _build_recipe_hints(recipe_db, allowed_verbs)
		if interrupt_mode and current_task_id_for_interrupt:
			extra_planner = "- 如果你决定继续当前任务，不提出新动作；本轮直接结束。"
			extra_grounder = "- 如果 Planner 决定继续当前任务，输出空 JSON 数组 []，表示 end_turn。"
			planner_recipe_hints = f"{planner_recipe_hints}\n{extra_planner}".strip() if planner_recipe_hints else extra_planner
			grounder_recipe_hints = f"{grounder_recipe_hints}\n{extra_grounder}".strip() if grounder_recipe_hints else extra_grounder
			yield_planner = "- YieldCurrentTask: 当你决定先放下当前任务去处理打断事件时，选择该动作。放下后任务按 task_policy 自动处理（通常保留为 Paused）。"
			yield_grounder = "- YieldCurrentTask: 仅在中断决策阶段可用，输出格式为 {\"verb\":\"YieldCurrentTask\",\"parameters\":{}}，不得提供 target_id。"
			planner_recipe_hints = f"{planner_recipe_hints}\n{yield_planner}".strip()
			grounder_recipe_hints = f"{grounder_recipe_hints}\n{yield_grounder}".strip()
		perception["mode_context"] = {
			**dict(agent_context.get("mode_context", {}) or {}),
			"available_verbs": sorted(list(allowed_verbs)),
			"available_verbs_with_duration": str(available_verbs_with_duration),
			"planner_recipe_hints": str(planner_recipe_hints),
			"grounder_recipe_hints": str(grounder_recipe_hints),
			"yield_current_task_available": bool(interrupt_mode and current_task_id_for_interrupt),
		}
		agent_context = _build_agent_context(perception, self_id)

		planner_template = _read_text(self.planner_template_path)
		planner_mapping = {
			"agent_name": str(agent_context.get("agent_name", "") or self_id),
			"personality_summary": str(agent_context.get("personality_summary", "") or ""),
			"common_knowledge_summary": str(agent_context.get("common_knowledge_summary", "") or ""),
			"long_term_memory": "",
			"mid_term_summary": str(agent_context.get("mid_term_summary", "") or ""),
			"current_goal": "",
			"current_plan": "",
			"current_task_id": str(agent_context.get("current_task_id", "") or ""),
			"current_task_summary": str(agent_context.get("current_task_summary", "") or ""),
			"vitals_text": str(agent_context.get("vitals_text", "") or "未知"),
			"active_interrupt_preset_id": str(agent_context.get("active_interrupt_preset_id", "") or ""),
			"available_interrupt_presets": ", ".join([str(x) for x in list(agent_context.get("available_interrupt_presets", []) or [])]),
			"interrupt_preset_summaries": str(agent_context.get("interrupt_preset_summaries_text", "") or ""),
			"tick": tick_str,
			"location_id": loc_id,
			"location_name": loc_name,
			"location_light_text": str(agent_context.get("location_light_text", "") or "light_level=2"),
			"available_verbs_with_duration": available_verbs_with_duration,
			"planner_recipe_hints": planner_recipe_hints,
			"map_topology_text": _map_topology_text(list(agent_context.get("map_topology", []) or [])),
			"reachable_locations_table": _reachable_locations_text_planner(reachable_locations),
			"can_start_conversation_here": str(can_start_conversation_here).lower(),
			"visible_entities_table": _entities_table_planner(visible_entities),
			"inventory_table": _inventory_table_planner(inventory),
			"recent_interactions_text": memory_context_text,
			"last_failure_summary": str(reason or ""),
			"planner_output_here": "",
		}
		planner_prompt = _fill_template(planner_template, planner_mapping)
		planner_messages = [
			{"role": "system", "content": self.PLANNER_SYSTEM_PROMPT},
			{"role": "user", "content": planner_prompt},
		]
		failure_attempt: dict[str, Any] | None = None
		if failure_context is not None:
			failure_attempt = {
				"attempt": len(list(failure_context.get("attempts", []) or [])) + 1,
				"planner": {
					"request": self._failure_request(
						model=str(getattr(self.llm, "planner_model", "") or ""),
						temperature=1,
						messages=planner_messages,
					),
				},
			}
			failure_context.setdefault("attempts", []).append(failure_attempt)
		focus_perception = {
			"self_id": self_id,
			"tick": tick,
			"location": {"id": loc_id, "name": loc_name},
			"mode": str(agent_context.get("mode", "") or ""),
			"mode_context": dict(agent_context.get("mode_context", {}) or {}),
			"current_task_id": str(agent_context.get("current_task_id", "") or ""),
			"current_task_type": str(agent_context.get("current_task_type", "") or ""),
			"current_task_status": str(agent_context.get("current_task_status", "") or ""),
			"vitals": dict(agent_context.get("vitals", {}) or {}),
			"entities": list(visible_entities),
			"inventory": list(inventory),
			"reachable_locations": list(reachable_locations),
			"short_term_memory_items": list(short_term_memory_items),
			"short_term_memory_text": short_term_memory_text,
			"available_verbs_with_duration": str(available_verbs_with_duration),
			"planner_recipe_hints": str(planner_recipe_hints),
		}
		self._focus_log(
			logger,
			"focus_planner_prompt",
			self_id,
			{
				"self_id": self_id,
				"system_prompt": self.PLANNER_SYSTEM_PROMPT.strip(),
				"user_prompt": planner_prompt,
				"planner_mapping": dict(planner_mapping),
				"perception": dict(focus_perception) if bool(self.focus_log_perception) else {},
			},
		)

		if bool(self.debug) or logger.enabled("trace", "llm"):
			debug_view = str(self.llm_debug_view or "").strip()
			context_data = {}
			if debug_view:
				keys = [k.strip() for k in debug_view.split(",") if k.strip()]
				filtered = {}
				for k in keys:
					if k in planner_mapping:
						filtered[k] = planner_mapping[k]
				context_data = {"planner_prompt_partial": filtered, "self_id": self_id}
			else:
				context_data = {
					"system_prompt": self.PLANNER_SYSTEM_PROMPT.strip(),
					"user_prompt": planner_prompt,
					"self_id": self_id,
				}
			logger.trace("llm", "planner_prompt", context=context_data)

		try:
			planner_raw = self.llm.planner_text(
				messages=planner_messages,
				temperature=1,
			).strip()
		except LLMRequestError as e:
			if failure_attempt is not None:
				failure_attempt["planner"]["error"] = str(e)
			self._record_failure_evidence(
				failure_context,
				kind="infrastructure",
				stage="planner_request",
				summary=str(e),
				details={"error_type": type(e).__name__, "error": str(e), "traceback": traceback.format_exc()},
			)
			logger.warn("llm", "planner_request_failed", context={"self_id": self_id, "error": str(e)})
			raise KernFailure(
				"LLM_PLANNER_REQUEST_FAILED",
				str(e),
				origin="llm",
				phase="planner_request",
				context={"actor_id": str(self_id or ""), "tick": int(tick_i), "failure_evidence": failure_context or {}},
			) from e
		planner_thought, intent = self._parse_planner_output(planner_raw)
		if failure_attempt is not None:
			failure_attempt["planner"].update({"response": planner_raw, "thought": planner_thought, "intent": intent})
		if bool(self.debug) or logger.enabled("debug", "llm"):
			logger.debug("llm", "planner_thought", context={"self_id": self_id, "thought": planner_thought})
			logger.debug("llm", "planner_intent", context={"self_id": self_id, "intent": intent})
		self._focus_log(
			logger,
			"focus_planner_output",
			self_id,
			{"self_id": self_id, "raw": planner_raw, "thought": planner_thought, "intent": intent},
		)

		grounder_template = _read_text(self.grounder_template_path)
		grounder_prompt = _fill_template(
			grounder_template,
			{
				"planner_intent_text": intent,
				"tick": tick_str,
				"location_id": loc_id,
				"location_name": loc_name,
				"location_light_text": str(agent_context.get("location_light_text", "") or "light_level=2"),
				"active_interrupt_preset_id": str((perception or {}).get("active_interrupt_preset_id", "") or ""),
				"available_interrupt_presets": ", ".join([str(x) for x in list((perception or {}).get("available_interrupt_presets", []) or [])]),
				"interrupt_preset_summaries": str(agent_context.get("interrupt_preset_summaries_text", "") or ""),
				"self_id": self_id,
				"vitals_text": str(agent_context.get("vitals_text", "") or "未知"),
				"reachable_locations_table": _reachable_locations_text(reachable_locations),
				"can_start_conversation_here": str(can_start_conversation_here).lower(),
				"visible_entities_table": _entities_table(visible_entities),
				"inventory_table": _inventory_table(inventory),
				"available_verbs_list": available_verbs_list,
				"grounder_recipe_hints": grounder_recipe_hints,
				"recent_interactions_text": memory_context_text,
				"verb": "",
				"target_id": "",
			},
		)
		grounder_messages = [
			{"role": "system", "content": self.GROUNDER_SYSTEM_PROMPT},
			{"role": "user", "content": grounder_prompt},
		]
		if failure_attempt is not None:
			failure_attempt["grounder"] = {
				"request": self._failure_request(
					model=str(getattr(self.llm, "grounder_model", "") or ""),
					temperature=1,
					messages=grounder_messages,
				)
			}

		if bool(self.debug) or logger.enabled("trace", "llm"):
			logger.trace(
				"llm",
				"grounder_prompt",
				context={
					"system_prompt": self.GROUNDER_SYSTEM_PROMPT.strip(),
					"user_prompt": grounder_prompt,
					"self_id": self_id,
				},
			)
		self._focus_log(
			logger,
			"focus_grounder_prompt",
			self_id,
			{
				"self_id": self_id,
				"system_prompt": self.GROUNDER_SYSTEM_PROMPT.strip(),
				"user_prompt": grounder_prompt,
				"grounder_hints": str(grounder_recipe_hints),
				"available_verbs_list": str(available_verbs_list),
				"perception": dict(focus_perception) if bool(self.focus_log_perception) else {},
			},
		)

		try:
			raw = self.llm.grounder_text(
				messages=grounder_messages,
				temperature=1,
			).strip()
		except LLMRequestError as e:
			if failure_attempt is not None:
				failure_attempt["grounder"]["error"] = str(e)
			self._record_failure_evidence(
				failure_context,
				kind="infrastructure",
				stage="grounder_request",
				summary=str(e),
				details={"error_type": type(e).__name__, "error": str(e), "traceback": traceback.format_exc()},
			)
			logger.warn("llm", "grounder_request_failed", context={"self_id": self_id, "error": str(e)})
			raise KernFailure(
				"LLM_GROUNDER_REQUEST_FAILED",
				str(e),
				origin="llm",
				phase="grounder_request",
				context={"actor_id": str(self_id or ""), "tick": int(tick_i), "failure_evidence": failure_context or {}},
			) from e
		if bool(self.debug) or logger.enabled("debug", "llm"):
			logger.debug("llm", "grounder_raw", context={"self_id": self_id, "raw": raw})
		self._focus_log(logger, "focus_grounder_raw", self_id, {"self_id": self_id, "raw": raw})

		# 1. Parse Failure -> System Error (Raise Exception)
		if failure_attempt is not None:
			failure_attempt["grounder"]["response"] = raw
		actions = self._parse_actions(raw)
		if failure_attempt is not None:
			failure_attempt["grounder"]["actions"] = [dict(item) for item in list(actions or []) if isinstance(item, dict)]
		if bool(self.debug) or logger.enabled("debug", "llm"):
			logger.debug("llm", "grounder_actions", context={"self_id": self_id, "actions": actions})
		self._focus_log(logger, "focus_grounder_actions", self_id, {"self_id": self_id, "actions": list(actions)})
		
		# 2. Logic Failure (Validation) -> Pass through to InteractionEngine
		# We no longer validate actions here; let the engine decide if the target is visible/valid.
		# This ensures that "hallucinated" actions are recorded as failed attempts in the world log.
		if ungroundable_notes:
			return [{"_workflow_note_type": "ungroundable", "reason": str(ungroundable_notes[-1] or "")}, *list(actions or [])]
		return actions

	def _parse_planner_output(self, raw: str) -> tuple[str, str]:
		s = str(raw or "").strip()
		if not s:
			return ("", "")
		pattern = re.compile(r"THOUGHT\s*:\s*(.*?)\s*INTENT\s*:\s*(.*)", flags=re.IGNORECASE | re.DOTALL)
		m = pattern.search(s)
		if m is not None:
			thought = str(m.group(1) or "").strip()
			intent = str(m.group(2) or "").strip()
			return (thought, intent or thought)
		lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
		thought = ""
		intent = ""
		for ln in lines:
			if re.match(r"^THOUGHT\s*:", ln, flags=re.IGNORECASE):
				thought = re.sub(r"^THOUGHT\s*:\s*", "", ln, flags=re.IGNORECASE).strip()
			elif re.match(r"^INTENT\s*:", ln, flags=re.IGNORECASE):
				intent = re.sub(r"^INTENT\s*:\s*", "", ln, flags=re.IGNORECASE).strip()
		if thought or intent:
			return (thought, intent or thought)
		return ("", s)

	def _parse_actions(self, raw: str) -> list[dict[str, Any]]:
		def _normalize_json_text(s: str) -> str:
			text = str(s or "").strip()
			if text.lower().startswith("json"):
				lines = text.splitlines()
				if len(lines) > 1:
					text = "\n".join(lines[1:]).strip()
			return text

		def _from_loaded(value: Any) -> list[dict[str, Any]] | None:
			# Preferred shape: top-level list[dict]
			if isinstance(value, list):
				out = [dict(item) for item in value if isinstance(item, dict)]
				return out
			# The grounder contract is a top-level list; only ungroundable uses an object.
			if isinstance(value, dict):
				dtype = str(value.get("type", "") or "").strip().lower()
				if dtype == "ungroundable":
					raise GroundingUngroundable(str(value.get("reason", "") or "Planner intent cannot be grounded with current actions."))
			return None

		def _extract_code_fence_bodies(s: str) -> list[str]:
			out: list[str] = []
			for m in re.finditer(r"```(?:json|JSON)?\s*([\s\S]*?)```", s):
				body = str(m.group(1) or "").strip()
				if body:
					out.append(body)
			return out

		def _extract_balanced_json_spans(s: str) -> list[str]:
			# Best-effort scanner for balanced JSON objects/arrays in mixed text.
			out: list[str] = []
			n = len(s)
			i = 0
			while i < n:
				ch = s[i]
				if ch not in "[{":
					i += 1
					continue
				stack = ["]" if ch == "[" else "}"]
				in_str = False
				escape = False
				j = i + 1
				while j < n:
					c = s[j]
					if in_str:
						if escape:
							escape = False
						elif c == "\\":
							escape = True
						elif c == '"':
							in_str = False
						j += 1
						continue
					if c == '"':
						in_str = True
						j += 1
						continue
					if c in "[{":
						stack.append("]" if c == "[" else "}")
						j += 1
						continue
					if c in "]}":
						if not stack or c != stack[-1]:
							break
						stack.pop()
						if not stack:
							out.append(s[i : j + 1])
							break
					j += 1
				i += 1
			return out

		def _try_parse_candidate(candidate: str) -> list[dict[str, Any]] | None:
			text = _normalize_json_text(candidate)
			if not text:
				return None
			try:
				loaded = json.loads(text)
			except Exception:
				return None
			return _from_loaded(loaded)

		s = str(raw or "").strip()
		if not s:
			raise ValueError("[LLM] Invalid JSON output from Grounder: <empty>")

		candidates: list[str] = [s]
		candidates.extend(_extract_code_fence_bodies(s))
		without_thought = re.sub(r"<thought>[\s\S]*?</thought>", "", s, flags=re.IGNORECASE).strip()
		if without_thought and without_thought != s:
			candidates.append(without_thought)

		for text in [s, without_thought]:
			if not text:
				continue
			candidates.extend(_extract_balanced_json_spans(text))

		seen: set[str] = set()
		for c in candidates:
			clean = str(c or "").strip()
			if not clean or clean in seen:
				continue
			seen.add(clean)
			actions = _try_parse_candidate(clean)
			if actions is not None:
				return actions

		raw_excerpt = s if len(s) <= 1200 else (s[:1200] + "...<truncated>")
		raise ValueError(f"[LLM] Invalid JSON output from Grounder: {raw_excerpt}")

	def decide_dialogue(self, perception: dict[str, Any], conversation_context: dict[str, Any], self_id: str | None = None) -> str:
		def _sanitize_dialogue_output(raw: str) -> str:
			s = str(raw or "").strip()
			if not s:
				return "PASS"

			# Remove complete <thought>...</thought> blocks first.
			s = re.sub(r"<\s*thought\s*>[\s\S]*?<\s*/\s*thought\s*>", "", s, flags=re.IGNORECASE).strip()

			# If model outputs an opening thought tag without close tag, drop from tag start.
			open_idx = re.search(r"<\s*thought\s*>", s, flags=re.IGNORECASE)
			if open_idx is not None:
				s = s[: open_idx.start()].strip()

			# If model still has "THOUGHT: ..." style chain-of-thought, keep content after the last line break.
			if re.search(r"\bTHOUGHT\s*:", s, flags=re.IGNORECASE):
				lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
				if lines:
					s = lines[-1]

			# Dialogue contract: one-line output only.
			if "\n" in s:
				s = s.splitlines()[0].strip()
			return s or "PASS"

		logger = get_logger()
		self_id = str(self_id or perception.get("self_id", "") or "")
		perception = _with_mode_context(perception if isinstance(perception, dict) else {}, "dialogue", conversation_context if isinstance(conversation_context, dict) else {})
		agent_context = _build_agent_context(perception, self_id)
		loc = agent_context.get("location", {}) or {}
		loc_id = str((loc or {}).get("id", "") or "")
		loc_name = str((loc or {}).get("name", "") or "")
		visible_entities = list(agent_context.get("visible_entities", []) or [])
		short_term_memory_text = str(agent_context.get("short_term_memory_text", "") or "")
		recent_interactions_text = str(agent_context.get("recent_interactions_text", "") or "")
		memory_context_text = "\n".join(
			text for text in (recent_interactions_text.strip(), short_term_memory_text.strip()) if text
		)
		inventory = list(agent_context.get("inventory", []) or [])
		reachable_locations = list(agent_context.get("reachable_locations", []) or [])
		mode_context = dict(agent_context.get("mode_context", {}) or {})
		utterance_index = int(mode_context.get("utterance_index", 0) or 0)
		max_utterances_per_tick = int(mode_context.get("max_utterances_per_tick", 0) or 0)
		remaining_utterances = max(0, max_utterances_per_tick - utterance_index)
		dialogue_template = _read_text(self.dialogue_template_path)
		dialogue_prompt = _fill_template(
			dialogue_template,
			{
				"self_id": self_id,
				"agent_name": str(agent_context.get("agent_name", "") or self_id),
				"personality_summary": str(agent_context.get("personality_summary", "") or ""),
				"common_knowledge_summary": str(agent_context.get("common_knowledge_summary", "") or ""),
				"mid_term_summary": str(agent_context.get("mid_term_summary", "") or ""),
				"current_task_summary": str(agent_context.get("current_task_summary", "") or ""),
				"mode": str(agent_context.get("mode", "") or ""),
				"location_id": loc_id,
				"location_name": loc_name,
				"location_light_text": str(agent_context.get("location_light_text", "") or "light_level=2"),
				"participants_table": _participants_table(list(mode_context.get("participants", []) or [])),
				"utterance_index": str(utterance_index),
				"max_utterances_per_tick": str(max_utterances_per_tick),
				"remaining_utterances_in_tick": str(remaining_utterances),
				"conversation_id": str(mode_context.get("conversation_id", "") or ""),
				"dialogue_phase": str(mode_context.get("dialogue_phase", "") or "dialogue"),
				"initiator_id": str(mode_context.get("initiator_id", "") or ""),
				"conversation_transcript": _conversation_transcript_text(list(mode_context.get("transcript", []) or [])),
				"visible_entities_table": _entities_table(visible_entities),
				"inventory_table": _inventory_table(inventory),
				"reachable_locations_table": _reachable_locations_text(reachable_locations),
				"recent_interactions_text": memory_context_text,
			},
		)
		dialogue_context = self._new_failure_context(
			context_type="llm_dialogue",
			actor_id=self_id,
			tick=int(agent_context.get("tick", 0) or 0),
			location_id=loc_id,
			perception=perception,
			reason=str(mode_context.get("dialogue_phase", "dialogue") or "dialogue"),
		)
		dialogue_messages = [
			{"role": "system", "content": self.DIALOGUE_SYSTEM_PROMPT},
			{"role": "user", "content": dialogue_prompt},
		]
		if dialogue_context is not None:
			dialogue_context["attempts"] = [
				{
					"attempt": 1,
					"dialogue": {
						"request": self._failure_request(
							model=str(getattr(self.llm, "planner_model", "") or ""),
							temperature=1,
							messages=dialogue_messages,
						),
					},
				}
			]
		if bool(self.debug) or logger.enabled("trace", "llm"):
			logger.trace("llm", "dialogue_prompt", context={"self_id": self_id, "system_prompt": self.DIALOGUE_SYSTEM_PROMPT.strip(), "user_prompt": dialogue_prompt})
		self._focus_log(
			logger,
			"focus_dialogue_prompt",
			self_id,
			{
				"self_id": self_id,
				"system_prompt": self.DIALOGUE_SYSTEM_PROMPT.strip(),
				"user_prompt": dialogue_prompt,
				"conversation_context": dict(conversation_context or {}),
				"perception": dict(perception or {}) if bool(self.focus_log_perception) else {},
			},
		)
		try:
			line = self.llm.planner_text(
				messages=dialogue_messages,
				temperature=1,
			).strip()
		except Exception as exc:
			if dialogue_context is not None:
				dialogue_context["attempts"][0]["dialogue"]["error"] = str(exc)
			self._record_failure_evidence(
				dialogue_context,
				kind="infrastructure" if isinstance(exc, LLMRequestError) else "llm_output",
				stage="dialogue_request",
				summary=str(exc),
				details={"error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()},
			)
			self._persist_trace(dialogue_context, "failed")
			raise KernFailure(
				"LLM_DIALOGUE_REQUEST_FAILED",
				str(exc),
				origin="llm",
				phase="dialogue_request",
				context={"actor_id": str(self_id or ""), "failure_evidence": dialogue_context or {}},
			) from exc
		if dialogue_context is not None:
			dialogue_context["attempts"][0]["dialogue"]["response"] = line
		line = _sanitize_dialogue_output(line)
		if dialogue_context is not None:
			dialogue_context["output"] = line
		self._persist_trace(dialogue_context, "completed")
		self._focus_log(logger, "focus_dialogue_output", self_id, {"self_id": self_id, "line": line})
		return str(line or "PASS")

	def decide_utterance(self, frame: DialogueFrame):
		line = self.decide_dialogue(
			perception=dict(frame.perception),
			conversation_context={
				"conversation_id": frame.conversation_id,
				"location_id": frame.location_id,
				"participants": list(frame.participants),
				"utterance_index": int(frame.utterance_index),
				"max_utterances_per_tick": int(frame.utterance_index + frame.remaining_utterances),
				"transcript": [dict(item) for item in frame.transcript],
				"dialogue_phase": "join_decision",
				"initiator_id": frame.initiator_id,
			},
			self_id=frame.speaker_id,
		)
		text = str(line or "").strip()
		return Pass() if not text or text.upper() == "PASS" else Speak(text)

	# _validate_actions removed



def build_default_llm_provider(
	config: dict[str, Any] | None = None,
	*,
	trace_recorder: LLMTraceRecorder | None = None,
) -> LLMActionProvider:
	"""
	Construct default two-layer LLM provider with provided model names.
	"""
	cfg = dict(config or {})
	def _cfg(key: str, default: str = "") -> str:
		if key in cfg and cfg.get(key) is not None:
			return str(cfg.get(key) or "").strip()
		return str(default or "").strip()
	def _cfg_bool(key: str, default: bool = False) -> bool:
		v = _cfg(key, "1" if default else "0").lower()
		return v in {"1", "true", "yes", "on"}
	def _cfg_json(key: str) -> dict[str, Any]:
		raw = _cfg(key, "")
		if not raw:
			return {}
		try:
			data = json.loads(raw)
		except Exception:
			return {}
		return dict(data) if isinstance(data, dict) else {}

	timeout_env = _cfg("LLM_TIMEOUT_SECONDS", "")
	retries_env = _cfg("LLM_MAX_RETRIES", "")
	backoff_env = _cfg("LLM_RETRY_BACKOFF_SECONDS", "")
	provider = _cfg("LLM_PROVIDER", "").lower() or "openai_compat"
	if provider == "gemini":
		client = GeminiClient(
			base_url=_cfg("GEMINI_BASE_URL", "") or "https://generativelanguage.googleapis.com",
			api_prefix=_cfg("GEMINI_API_PREFIX", "") or "/v1beta",
			api_key=_cfg("GEMINI_API_KEY", "") or "REPLACE_ME",
			timeout_seconds=int(timeout_env) if timeout_env else 60,
			max_retries=int(retries_env) if retries_env else 2,
			retry_backoff_seconds=float(backoff_env) if backoff_env else 1.0,
		)
		planner_model = _cfg("LLM_PLANNER_MODEL", "") or "gemini-1.5-pro"
		grounder_model = _cfg("LLM_GROUNDER_MODEL", "") or "gemini-1.5-flash"
	else:
		client = OpenAICompatClient(
			base_url=_cfg("LLM_BASE_URL", "") or "https://api.aabao.top",
			api_prefix=_cfg("LLM_API_PREFIX", "") or "/v1",
			api_key=_cfg("LLM_API_KEY", "") or "REPLACE_ME",
			timeout_seconds=int(timeout_env) if timeout_env else 60,
			max_retries=int(retries_env) if retries_env else 2,
			retry_backoff_seconds=float(backoff_env) if backoff_env else 1.0,
		)
		planner_model = _cfg("LLM_PLANNER_MODEL", "") or "gemini-3-pro-preview"
		grounder_model = _cfg("LLM_GROUNDER_MODEL", "") or "gemini-3-flash-preview"
	request_extra = _cfg_json("LLM_REQUEST_EXTRA_JSON")
	llm = DualModelLLM(client=client, planner_model=planner_model, grounder_model=grounder_model, request_extra=request_extra)
	return LLMActionProvider(
		llm=llm,
		debug=False,
		focus_agent_id=_cfg("LLM_FOCUS_AGENT_ID", ""),
		focus_log_prompts=_cfg_bool("LLM_FOCUS_LOG_PROMPTS", False),
		focus_log_perception=_cfg_bool("LLM_FOCUS_LOG_PERCEPTION", True),
		llm_debug_view=_cfg("LLM_DEBUG_VIEW", ""),
		trace_recorder=trace_recorder,
	)

