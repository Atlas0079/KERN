from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..log_manager import get_logger
from ..llm.openai_compat_client import DualModelLLM, OpenAICompatClient, LLMRequestError
from ..llm.gemini_client import GeminiClient


def _repo_root() -> Path:
	# newserver/agents/llm_action_provider.py -> repo root
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
				done_condition = str(t.get("done_condition_id", "") or "").strip()
				extras: list[str] = []
				if required_tool:
					extras.append(f"requires:{required_tool}")
				if done_condition:
					extras.append(f"done_when:{done_condition}")
				extra_text = f",{','.join(extras)}" if extras else ""
				summaries.append(
					f"{ttype}({prog:g}/{req:g},{status or 'Unknown'},{'available' if avail else f'assigned:{assigned_cnt}'}{extra_text})"
				)
			if summaries:
				task_text = f", tasks: [{'; '.join(summaries)}]"
		lines.append(f"- id: {eid}, name: {name}, tags: {list(tags)}, where: {where}{task_text}")
	return "\n".join(lines) if lines else "(No visible entities)"


def _entities_table_planner(entities: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for e in list(entities or []):
		if not isinstance(e, dict):
			continue
		name = str(e.get("name", "") or "")
		tags = [str(x) for x in list(e.get("tags", []) or [])]
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
				assigned = t.get("assigned_agent_ids", []) or []
				assigned_cnt = len(list(assigned)) if isinstance(assigned, list) else 0
				avail = bool(t.get("is_available", False))
				required_tool = str(t.get("required_item_tag", "") or "").strip()
				extra = f"，需工具:{required_tool}" if required_tool else ""
				summaries.append(f"{ttype}({status or 'Unknown'},{'可接取' if avail else f'已分配:{assigned_cnt}'}{extra})")
			if summaries:
				task_text = f"，任务: {'; '.join(summaries)}"
		lines.append(f"- {name}（tags:{tags}，{where}{task_text}）")
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
		conditions = item.get("conditions", []) or []
		lines.append(f"- id: {eid}, name: {name}, tags: {list(tags)}, conditions: {list(conditions)}, slot: {slot}")
	return "\n".join(lines) if lines else "(Empty)"


def _inventory_table_planner(inventory: list[dict[str, Any]]) -> str:
	lines: list[str] = []
	for item in list(inventory or []):
		if not isinstance(item, dict):
			continue
		name = str(item.get("name", "") or "")
		tags = [str(x) for x in list(item.get("tags", []) or [])]
		conditions = [str(x) for x in list(item.get("conditions", []) or [])]
		lines.append(f"- {name}（tags:{tags}，状态:{conditions if conditions else '无'}）")
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
	def _inv_has_condition(tag: str, condition_id: str) -> bool:
		for it in list(inventory or []):
			if not isinstance(it, dict):
				continue
			tags = [str(x) for x in list(it.get("tags", []) or [])]
			if str(tag) not in tags:
				continue
			conds = [str(x) for x in list(it.get("conditions", []) or [])]
			if str(condition_id) in conds:
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
		if verb == "ShootRevolver" and not _inv_has_condition("revolver", "revolver_loaded"):
			continue
		if verb == "ReloadRevolver" and (not _inv_has_condition("revolver", "revolver_unloaded") or not _inv_has_tag("bullet")):
			continue
		if verb == "ShootShockPistol" and not _inv_has_condition("shock_pistol", "shock_charged"):
			continue
		if verb == "RechargeShockPistol" and not _inv_has_condition("shock_pistol", "shock_uncharged"):
			continue
		process = recipe.get("process", {}) or {}
		required_progress = float((process or {}).get("required_progress", 0) or 0)
		verbs[verb] = "duration" if required_progress != 0 else "instant"

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
	- Memory module not implemented yet: Planner uses perception-filtered "recent interaction narrative" directly as detailed event stream input.
	"""

	llm: DualModelLLM
	planner_template_path: Path = _repo_root() / "Data" / "LLMContext_Planner.md"
	grounder_template_path: Path = _repo_root() / "Data" / "LLMContext_Grounder.md"
	dialogue_template_path: Path = _repo_root() / "Data" / "LLMContext_Dialogue.md"
	debug: bool = False
	consecutive_failures: int = 0
	cooldown_until_tick: int = -1
	last_cooldown_warn_tick: int = -1
	focus_agent_id: str = ""
	focus_log_prompts: bool = False
	focus_log_perception: bool = True
	llm_failure_threshold: int = 3
	llm_failure_cooldown_ticks: int = 60
	llm_debug_view: str = ""

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
1. 必须输出一个 JSON 数组，数组元素是 Action 对象。
2. Action 对象格式为：`{"verb": "verb", "parameters": {}}`，并且在需要时可以包含 `"target_id"`。
3. 只能使用“可用动词列表”中的动词。
4. 对于非 meta 动词，通常需要提供 `target_id`，且必须来自“可见实体列表”或“背包列表”；但 Talk 是例外（不得提供 target_id）。对于 meta 动词，你不得提供 `target_id`（系统会自动填充为你自己）。
5. 对于耗时动作，它必须是序列中的最后一个动作（因为会触发 Task 并占用行动权）。
6. 不要在 JSON 外层添加任何 Markdown 标签（如 ```json），只输出纯 JSON 字符串。

**动词特定参数规则（重要）：**
- SwitchInterruptPreset（meta）：parameters 必须包含 `{"preset_id": "<available_interrupt_presets 中的一个>"}`，且不得提供 target_id。
- UpdateInterruptRuleParam（meta）：parameters 必须包含 `{"preset_id": "...", "rule_type": "...", "key": "...", "value": <任意值>}`，且不得提供 target_id。
- InspectInterruptPresets（meta）：可选参数 `{"preset_id": "<可选>"}`，且不得提供 target_id。
- Travel（non-meta）：target_id 必须是 self id，parameters 必须包含 `{"to_location_id": "<reachable_locations.to_location_id 之一>"}`。
- Talk（non-meta）：不得提供 target_id；parameters 必须包含 `{"text": "<非空开场白>"}`。执行后会触发“当前地点群体对话”，该 text 作为第一轮发言，然后同地点其他角色按轮次继续。
- ContinueCurrentTask（non-meta，仅在中断决策阶段可用）：不得提供 target_id；parameters 必须为空对象 `{}`。
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

	def _failure_threshold(self) -> int:
		try:
			v = int(self.llm_failure_threshold)
		except Exception:
			v = 3
		return max(1, v)

	def _cooldown_ticks(self) -> int:
		try:
			v = int(self.llm_failure_cooldown_ticks)
		except Exception:
			v = 60
		return max(0, v)

	def _on_llm_failure(self, logger: Any, self_id: str, tick: int | None, stage: str, error: str) -> None:
		self.consecutive_failures = int(self.consecutive_failures) + 1
		logger.warn("llm", f"{stage}_request_failed", context={"self_id": self_id, "error": str(error)})
		threshold = self._failure_threshold()
		if self.consecutive_failures < threshold:
			return
		cooldown = self._cooldown_ticks()
		base_tick = int(tick or 0)
		self.cooldown_until_tick = int(base_tick + cooldown)
		logger.warn(
			"llm",
			"request_cooldown",
			context={
				"self_id": self_id,
				"stage": stage,
				"consecutive_failures": int(self.consecutive_failures),
				"threshold": int(threshold),
				"cooldown_ticks": int(cooldown),
				"cooldown_until_tick": int(self.cooldown_until_tick),
			},
		)

	def _is_focus_agent(self, self_id: str) -> bool:
		fid = str(self.focus_agent_id or "").strip()
		return bool(fid) and str(self_id or "").strip() == fid

	def _focus_log(self, logger: Any, event: str, self_id: str, context: dict[str, Any]) -> None:
		if not bool(self.focus_log_prompts):
			return
		if not self._is_focus_agent(self_id):
			return
		logger.warn("llm", str(event), context=dict(context or {}))

	def decide(self, perception: dict[str, Any], reason: str, self_id: str | None = None) -> list[dict[str, Any]]:
		logger = get_logger()
		self_id = str(self_id or perception.get("self_id", "") or "")
		visible_entities = list((perception or {}).get("entities", []) or [])
		reachable_locations = list((perception or {}).get("reachable_locations", []) or [])
		can_start_conversation_here = bool((perception or {}).get("can_start_conversation_here", True))
		short_term_memory_text = str((perception or {}).get("short_term_memory_text", "") or "")
		short_term_memory_items = list((perception or {}).get("short_term_memory_items", []) or [])
		inventory = list((perception or {}).get("inventory", []) or [])
		loc = (perception or {}).get("location", {}) or {}
		loc_id = str((loc or {}).get("id", "") or "")
		loc_name = str((loc or {}).get("name", "") or "")
		tick = (perception or {}).get("tick", None)
		tick_str = str(tick) if tick is not None else ""
		tick_i: int | None = None
		try:
			tick_i = int(tick) if tick is not None else None
		except Exception:
			tick_i = None
		if tick_i is not None and int(self.cooldown_until_tick) > int(tick_i):
			if int(self.last_cooldown_warn_tick) != int(tick_i):
				self.last_cooldown_warn_tick = int(tick_i)
				logger.warn(
					"llm",
					"request_skipped_in_cooldown",
					context={"self_id": self_id, "tick": int(tick_i), "cooldown_until_tick": int(self.cooldown_until_tick)},
				)
			return []

		recipe_db: dict[str, Any] = {}
		# Convention: perception can carry recipe_db (Injected by upper layer); otherwise degrade to no available verbs
		if isinstance((perception or {}).get("recipe_db", None), dict):
			recipe_db = dict((perception or {}).get("recipe_db") or {})

		available_verbs_list, available_verbs_with_duration, allowed_verbs = _build_available_verbs(
			recipe_db, visible_entities, inventory, reachable_locations, can_start_conversation_here
		)
		interrupt_mode = bool((perception or {}).get("interrupt_decision_mode", False))
		current_task_id_for_interrupt = str((perception or {}).get("current_task_id", "") or "")
		if interrupt_mode and current_task_id_for_interrupt:
			allowed_verbs = set(allowed_verbs)
			allowed_verbs.add("ContinueCurrentTask")
			verb_lines = [f"- {v}" for v in sorted(allowed_verbs)]
			available_verbs_list = "\n".join(verb_lines) if verb_lines else "(No available verbs)"
			if "ContinueCurrentTask" not in str(available_verbs_with_duration):
				available_verbs_with_duration = (
					f"{available_verbs_with_duration}\n- ContinueCurrentTask: instant".strip()
					if available_verbs_with_duration
					else "- ContinueCurrentTask: instant"
				)
		planner_recipe_hints, grounder_recipe_hints = _build_recipe_hints(recipe_db, allowed_verbs)
		if interrupt_mode and current_task_id_for_interrupt:
			extra_planner = "- ContinueCurrentTask: 当你被中断但判断当前任务更优先时，选择该动作以继续当前任务，不切换目标。"
			extra_grounder = "- ContinueCurrentTask: 仅在中断决策阶段可用，输出格式为 {\"verb\":\"ContinueCurrentTask\",\"parameters\":{}}，不得提供 target_id。"
			planner_recipe_hints = f"{planner_recipe_hints}\n{extra_planner}".strip() if planner_recipe_hints else extra_planner
			grounder_recipe_hints = f"{grounder_recipe_hints}\n{extra_grounder}".strip() if grounder_recipe_hints else extra_grounder

		summaries = list((perception or {}).get("interrupt_preset_summaries", []) or [])
		summ_lines: list[str] = []
		for it in summaries:
			if not isinstance(it, dict):
				continue
			pid = str(it.get("preset_id", "") or "")
			desc = str(it.get("description", "") or "")
			if pid and desc:
				summ_lines.append(f"- {pid}: {desc}")
			elif pid:
				summ_lines.append(f"- {pid}")
		interrupt_preset_summaries_text = "\n".join(summ_lines) if summ_lines else ""

		planner_template = _read_text(self.planner_template_path)
		planner_mapping = {
			"agent_name": str((perception or {}).get("agent_name", "") or self_id),
			"personality_summary": str((perception or {}).get("personality_summary", "") or ""),
			"common_knowledge_summary": str((perception or {}).get("common_knowledge_summary", "") or ""),
			"long_term_memory": "",
			"mid_term_summary": str((perception or {}).get("mid_term_summary", "") or ""),
			"current_goal": "",
			"current_plan": "",
			"current_task_id": str((perception or {}).get("current_task_id", "") or ""),
			"active_interrupt_preset_id": str((perception or {}).get("active_interrupt_preset_id", "") or ""),
			"available_interrupt_presets": ", ".join([str(x) for x in list((perception or {}).get("available_interrupt_presets", []) or [])]),
			"interrupt_preset_summaries": interrupt_preset_summaries_text,
			"tick": tick_str,
			"location_id": loc_id,
			"location_name": loc_name,
			"available_verbs_with_duration": available_verbs_with_duration,
			"planner_recipe_hints": planner_recipe_hints,
			"map_topology_text": _map_topology_text(list((perception or {}).get("map_topology", []) or [])),
			"reachable_locations_table": _reachable_locations_text_planner(reachable_locations),
			"can_start_conversation_here": str(can_start_conversation_here).lower(),
			"visible_entities_table": _entities_table_planner(visible_entities),
			"inventory_table": _inventory_table_planner(inventory),
			"recent_interactions_text": short_term_memory_text,
			"last_failure_summary": str(reason or ""),
			"planner_output_here": "",
		}
		planner_prompt = _fill_template(planner_template, planner_mapping)
		focus_perception = {
			"self_id": self_id,
			"tick": tick,
			"location": {"id": loc_id, "name": loc_name},
			"current_task_id": str((perception or {}).get("current_task_id", "") or ""),
			"current_task_type": str((perception or {}).get("current_task_type", "") or ""),
			"current_task_status": str((perception or {}).get("current_task_status", "") or ""),
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
				messages=[
					{"role": "system", "content": self.PLANNER_SYSTEM_PROMPT},
					{"role": "user", "content": planner_prompt},
				],
				temperature=0.4,
			).strip()
		except LLMRequestError as e:
			self._on_llm_failure(logger, self_id, tick_i, "planner", str(e))
			return []
		planner_thought, intent = self._parse_planner_output(planner_raw)
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
				"active_interrupt_preset_id": str((perception or {}).get("active_interrupt_preset_id", "") or ""),
				"available_interrupt_presets": ", ".join([str(x) for x in list((perception or {}).get("available_interrupt_presets", []) or [])]),
				"interrupt_preset_summaries": interrupt_preset_summaries_text,
				"self_id": self_id,
				"reachable_locations_table": _reachable_locations_text(reachable_locations),
				"can_start_conversation_here": str(can_start_conversation_here).lower(),
				"visible_entities_table": _entities_table(visible_entities),
				"inventory_table": _inventory_table(inventory),
				"available_verbs_list": available_verbs_list,
				"grounder_recipe_hints": grounder_recipe_hints,
				"recent_interactions_text": short_term_memory_text,
				"verb": "",
				"target_id": "",
			},
		)

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
				messages=[
					{"role": "system", "content": self.GROUNDER_SYSTEM_PROMPT},
					{"role": "user", "content": grounder_prompt},
				],
				temperature=0.2,
			).strip()
		except LLMRequestError as e:
			self._on_llm_failure(logger, self_id, tick_i, "grounder", str(e))
			return []
		self.consecutive_failures = 0
		if bool(self.debug) or logger.enabled("debug", "llm"):
			logger.debug("llm", "grounder_raw", context={"self_id": self_id, "raw": raw})
		self._focus_log(logger, "focus_grounder_raw", self_id, {"self_id": self_id, "raw": raw})

		# 1. Parse Failure -> System Error (Raise Exception)
		actions = self._parse_actions(raw)
		if bool(self.debug) or logger.enabled("debug", "llm"):
			logger.debug("llm", "grounder_actions", context={"self_id": self_id, "actions": actions})
		self._focus_log(logger, "focus_grounder_actions", self_id, {"self_id": self_id, "actions": list(actions)})
		
		# 2. Logic Failure (Validation) -> Pass through to InteractionEngine
		# We no longer validate actions here; let the engine decide if the target is visible/valid.
		# This ensures that "hallucinated" actions are recorded as failed attempts in the world log.
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
		# Allow model output ```json fenced block```, try best effort extraction
		s = str(raw or "").strip()
		if "```" in s:
			parts = s.split("```")
			# Select the part containing '['
			for p in parts:
				if "[" in p and "]" in p:
					s = p
					break
		s = s.strip()
		# Remove possible "json" tag line
		if s.lower().startswith("json"):
			s = "\n".join(s.splitlines()[1:]).strip()

		try:
			data = json.loads(s)
		except Exception as e:
			# Critical: Malformed JSON -> System Error
			# We must stop the simulation or force a crash so the developer can fix the prompt/model.
			raise ValueError(f"[LLM] Invalid JSON output from Grounder: {s}") from e
			
		if not isinstance(data, list):
			# Also a format error
			raise ValueError(f"[LLM] Grounder output is not a list: {s}")

		out: list[dict[str, Any]] = []
		for item in data:
			if isinstance(item, dict):
				out.append(dict(item))
		return out

	def decide_dialogue(self, perception: dict[str, Any], conversation_context: dict[str, Any], self_id: str | None = None) -> str:
		logger = get_logger()
		self_id = str(self_id or perception.get("self_id", "") or "")
		loc = (perception or {}).get("location", {}) or {}
		loc_id = str((loc or {}).get("id", "") or "")
		loc_name = str((loc or {}).get("name", "") or "")
		visible_entities = list((perception or {}).get("entities", []) or [])
		short_term_memory_text = str((perception or {}).get("short_term_memory_text", "") or "")
		dialogue_template = _read_text(self.dialogue_template_path)
		dialogue_prompt = _fill_template(
			dialogue_template,
			{
				"self_id": self_id,
				"agent_name": str((perception or {}).get("agent_name", "") or self_id),
				"personality_summary": str((perception or {}).get("personality_summary", "") or ""),
				"common_knowledge_summary": str((perception or {}).get("common_knowledge_summary", "") or ""),
				"location_id": loc_id,
				"location_name": loc_name,
				"participants_table": "\n".join([f"- {x}" for x in list((conversation_context or {}).get("participants", []) or [])]),
				"utterance_index": str((conversation_context or {}).get("utterance_index", 0)),
				"max_utterances_per_tick": str((conversation_context or {}).get("max_utterances_per_tick", 0)),
				"visible_entities_table": _entities_table(visible_entities),
				"recent_interactions_text": short_term_memory_text,
			},
		)
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
		line = self.llm.planner_text(
			messages=[
				{"role": "system", "content": self.DIALOGUE_SYSTEM_PROMPT},
				{"role": "user", "content": dialogue_prompt},
			],
			temperature=0.7,
		).strip()
		if "\n" in line:
			line = line.splitlines()[0].strip()
		self._focus_log(logger, "focus_dialogue_output", self_id, {"self_id": self_id, "line": line})
		return str(line or "PASS")

	# _validate_actions removed



def build_default_llm_provider(config: dict[str, Any] | None = None) -> LLMActionProvider:
	"""
	Construct default two-layer LLM provider with provided model names.
	"""
	cfg = dict(config or {})
	def _cfg(key: str, default: str = "") -> str:
		if key in cfg and cfg.get(key) is not None:
			return str(cfg.get(key) or "").strip()
		return str(__import__("os").environ.get(key, default) or "").strip()
	def _cfg_bool(key: str, default: bool = False) -> bool:
		v = _cfg(key, "1" if default else "0").lower()
		return v in {"1", "true", "yes", "on"}
	def _cfg_int(key: str, default: int) -> int:
		raw = _cfg(key, str(default))
		try:
			return int(raw)
		except Exception:
			return int(default)

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
	llm = DualModelLLM(client=client, planner_model=planner_model, grounder_model=grounder_model)
	return LLMActionProvider(
		llm=llm,
		debug=False,
		focus_agent_id=_cfg("LLM_FOCUS_AGENT_ID", ""),
		focus_log_prompts=_cfg_bool("LLM_FOCUS_LOG_PROMPTS", False),
		focus_log_perception=_cfg_bool("LLM_FOCUS_LOG_PERCEPTION", True),
		llm_failure_threshold=_cfg_int("LLM_FAILURE_THRESHOLD", 3),
		llm_failure_cooldown_ticks=_cfg_int("LLM_FAILURE_COOLDOWN_TICKS", 60),
		llm_debug_view=_cfg("LLM_DEBUG_VIEW", ""),
	)

