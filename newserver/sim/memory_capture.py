from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models.components import MemoryComponent


@dataclass
class MemoryCaptureSystem:
	min_importance: float = 0.45

	def _iter_controllable_agent_ids(self, ws: Any) -> list[str]:
		out: list[str] = []
		for ent in list(getattr(ws, "entities", {}).values()):
			if ent is None:
				continue
			ctrl = ent.get_component("AgentControlComponent")
			if ctrl is None or not bool(getattr(ctrl, "enabled", True)):
				continue
			agent_id = str(getattr(ent, "entity_id", "") or "")
			if agent_id:
				out.append(agent_id)
		return out

	def _ensure_memory_component(self, ws: Any, agent_id: str) -> tuple[Any | None, str]:
		agent = ws.get_entity_by_id(agent_id) if hasattr(ws, "get_entity_by_id") else None
		if agent is None:
			return (None, "")
		mem = agent.get_component("MemoryComponent")
		if not isinstance(mem, MemoryComponent):
			mem = MemoryComponent()
			agent.add_component("MemoryComponent", mem)
		loc = ws.get_location_of_entity(agent_id) if hasattr(ws, "get_location_of_entity") else None
		agent_loc_id = str(getattr(loc, "location_id", "") or "")
		return (mem, agent_loc_id)

	def _capture_event_for_agent(self, ws: Any, agent_id: str, item: dict[str, Any]) -> None:
		mem, agent_loc_id = self._ensure_memory_component(ws, agent_id)
		if not isinstance(mem, MemoryComponent):
			return
		seq = int((item or {}).get("seq", 0) or 0)
		if seq <= int(mem.last_event_seq_seen or 0):
			return
		entry = self._event_to_memory_entry(ws, agent_id, agent_loc_id, item)
		if entry is not None and float(entry.get("importance", 0.0) or 0.0) >= float(self.min_importance):
			mem.add_short_term(entry)
		mem.last_event_seq_seen = max(int(mem.last_event_seq_seen or 0), int(seq))

	def _capture_interaction_for_agent(self, ws: Any, agent_id: str, item: dict[str, Any]) -> None:
		mem, agent_loc_id = self._ensure_memory_component(ws, agent_id)
		if not isinstance(mem, MemoryComponent):
			return
		seq = int((item or {}).get("seq", 0) or 0)
		if seq <= int(mem.last_interaction_seq_seen or 0):
			return
		entry = self._interaction_to_memory_entry(ws, agent_id, agent_loc_id, item)
		if entry is not None and float(entry.get("importance", 0.0) or 0.0) >= float(self.min_importance):
			mem.add_short_term(entry)
		mem.last_interaction_seq_seen = max(int(mem.last_interaction_seq_seen or 0), int(seq))

	def capture_from_event(self, ws: Any, item: dict[str, Any]) -> None:
		if not isinstance(item, dict):
			return
		for agent_id in self._iter_controllable_agent_ids(ws):
			self._capture_event_for_agent(ws, agent_id, item)

	def capture_from_interaction(self, ws: Any, item: dict[str, Any]) -> None:
		if not isinstance(item, dict):
			return
		for agent_id in self._iter_controllable_agent_ids(ws):
			self._capture_interaction_for_agent(ws, agent_id, item)

	def _maybe_summarize_agent(self, ws: Any, agent_id: str) -> None:
		mem, _agent_loc_id = self._ensure_memory_component(ws, agent_id)
		if not isinstance(mem, MemoryComponent):
			return
		now_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		if not mem.should_summarize_mid_term(now_tick):
			return
		prep_items = [dict(x) for x in list(mem.mid_term_prep_queue or []) if isinstance(x, dict)]
		if not prep_items:
			return
		summary = self._summarize_mid_term(ws, agent_id, prep_items)
		if not summary:
			return
		ticks = [int((x or {}).get("tick", 0) or 0) for x in prep_items]
		tick_start = min(ticks) if ticks else now_tick
		tick_end = max(ticks) if ticks else now_tick
		tags = self._top_tags(prep_items, 5)
		mem.add_mid_term_summary(summary, tick_start, tick_end, tags)
		mem.mid_term_prep_queue = []

	def summarize_all(self, ws: Any) -> None:
		for agent_id in self._iter_controllable_agent_ids(ws):
			self._maybe_summarize_agent(ws, agent_id)

	def capture_all(self, ws: Any) -> None:
		for agent_id in self._iter_controllable_agent_ids(ws):
			self.capture_for_agent(ws, agent_id)

	def capture_for_agent(self, ws: Any, agent_id: str) -> None:
		mem, _agent_loc_id = self._ensure_memory_component(ws, agent_id)
		if not isinstance(mem, MemoryComponent):
			return
		for item in list(getattr(ws, "event_log", []) or []):
			if not isinstance(item, dict):
				continue
			self._capture_event_for_agent(ws, agent_id, item)
		for item in list(getattr(ws, "interaction_log", []) or []):
			if not isinstance(item, dict):
				continue
			self._capture_interaction_for_agent(ws, agent_id, item)
		self._maybe_summarize_agent(ws, agent_id)

	def _event_to_memory_entry(self, ws: Any, agent_id: str, agent_loc_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
		ev = item.get("event", {}) or {}
		if not isinstance(ev, dict):
			return None
		ev_type = str(ev.get("type", "") or "")
		drop_event_types = {
			"TickAdvanced",
			"AdvanceTick",
			"ReactionTriggered",
			"ReactionApplied",
			"PropertyModified",
			"ConditionAdded",
			"ConditionRemoved",
			"CooldownSet",
			"MemoryNoteAdded",
			"TaskProgressed",
			"ConversationStarted",
			"ConversationSpoken",
			"ConversationEnded",
		}
		if not ev_type or ev_type in drop_event_types:
			return None
		actor_id = str(item.get("actor_id", "") or "")
		location_id = str(item.get("location_id", "") or "")
		event_entity_id = str(ev.get("entity_id", "") or "")
		is_self_related = bool(actor_id == agent_id or event_entity_id == agent_id)
		is_same_location = bool(location_id and location_id == agent_loc_id)
		if not is_self_related and not is_same_location:
			return None
		topic = "event"
		importance = 0.5
		if "Task" in ev_type:
			topic = "task"
			importance = 0.65 if is_self_related else 0.5
		elif ev_type in {"KillEntity", "EntityDestroyed"}:
			topic = "threat"
			importance = 0.85
		elif ev_type.startswith("Conversation"):
			topic = "social"
			importance = 0.55
		content = self._event_content(ev_type, ev)
		return {
			"tick": int(item.get("tick", 0) or 0),
			"time_str": "",
			"type": "event",
			"topic": topic,
			"importance": importance,
			"location_id": location_id,
			"actor_id": actor_id,
			"target_id": event_entity_id,
			"content": content,
			"source": {"kind": "event_log", "seq": int(item.get("seq", 0) or 0)},
		}

	def _interaction_to_memory_entry(self, ws: Any, agent_id: str, agent_loc_id: str, item: dict[str, Any]) -> dict[str, Any] | None:
		if bool(item.get("is_reaction", False)):
			return None
		actor_id = str(item.get("actor_id", "") or "")
		actor_name = str(item.get("actor_name", "") or actor_id)
		target_id = str(item.get("target_id", "") or "")
		target_name = str(item.get("target_name", "") or target_id)
		location_id = str(item.get("location_id", "") or "")
		verb = str(item.get("verb", "") or "")
		status = str(item.get("status", "") or "")
		reason = str(item.get("reason", "") or "")
		recipe_id = str(item.get("recipe_id", "") or "")
		speech = str(item.get("speech", "") or "").strip()
		is_dialogue = bool(item.get("is_dialogue", False)) or verb == "Say"
		is_self_related = bool(actor_id == agent_id or target_id == agent_id)
		is_same_location = bool(location_id and location_id == agent_loc_id)
		if not is_self_related and not is_same_location:
			return None
		if is_dialogue:
			importance = 0.8 if is_self_related else 0.65
			topic = "social_dialogue"
			content = f"{actor_name}：{speech}" if speech else f"{actor_name}：{verb} {status}"
		else:
			importance = 0.8 if is_self_related and status == "failed" else 0.65 if is_self_related else 0.5
			topic = "action_failed" if status == "failed" else "action_success"
			content = self._interaction_content(
				ws=ws,
				item=item,
				actor_name=actor_name,
				target_name=target_name,
				verb=verb,
				status=status,
				reason=reason,
				recipe_id=recipe_id,
			)
		return {
			"tick": int(item.get("tick", 0) or 0),
			"time_str": "",
			"type": "interaction",
			"topic": topic,
			"importance": importance,
			"location_id": location_id,
			"actor_id": actor_id,
			"target_id": target_id,
			"content": content,
			"source": {"kind": "interaction_log", "seq": int(item.get("seq", 0) or 0)},
		}

	def _interaction_content(
		self,
		ws: Any,
		item: dict[str, Any],
		actor_name: str,
		target_name: str,
		verb: str,
		status: str,
		reason: str,
		recipe_id: str,
	) -> str:
		recipe = self._recipe_by_id(ws, recipe_id)
		template = ""
		if isinstance(recipe, dict):
			if status == "failed":
				template = str(recipe.get("narrative_fail", "") or "")
			else:
				template = str(recipe.get("narrative_success", "") or "")
		values = dict(item or {})
		values["actor"] = actor_name
		values["target"] = target_name
		values["reason"] = reason
		if template:
			return self._render_text_template(template, values)
		if status == "failed":
			if target_name:
				return f"{actor_name}对{target_name}执行{verb}失败：{reason or 'unknown'}"
			return f"{actor_name}执行{verb}失败：{reason or 'unknown'}"
		if target_name:
			return f"{actor_name}对{target_name}执行了{verb}"
		return f"{actor_name}执行了{verb}"

	def _recipe_by_id(self, ws: Any, recipe_id: str) -> dict[str, Any] | None:
		rid = str(recipe_id or "").strip()
		if not rid:
			return None
		services = getattr(ws, "services", {}) or {}
		engine = services.get("interaction_engine")
		recipe_db = getattr(engine, "recipe_db", {}) if engine is not None else {}
		if not isinstance(recipe_db, dict):
			return None
		recipe = recipe_db.get(rid)
		return dict(recipe) if isinstance(recipe, dict) else None

	def _render_text_template(self, template: str, values: dict[str, Any]) -> str:
		out = str(template or "")
		for k, v in (values or {}).items():
			key = str(k)
			out = out.replace("{" + key + "}", str(v if v is not None else ""))
		return out

	def _event_content(self, ev_type: str, ev: dict[str, Any]) -> str:
		if ev_type.startswith("Task"):
			task_id = str(ev.get("task_id", "") or "")
			if task_id:
				return f"{ev_type} {task_id}"
		if ev_type.startswith("Conversation"):
			cid = str(ev.get("conversation_id", "") or "")
			if cid:
				return f"{ev_type} {cid}"
		return ev_type

	def _summarize_mid_term(self, ws: Any, agent_id: str, prep_items: list[dict[str, Any]]) -> str:
		provider = (getattr(ws, "services", {}) or {}).get("default_action_provider")
		if provider is not None and hasattr(provider, "llm"):
			llm = getattr(provider, "llm", None)
			if llm is not None and hasattr(llm, "planner_text"):
				lines: list[str] = []
				for item in prep_items[-30:]:
					if not isinstance(item, dict):
						continue
					tick = int(item.get("tick", 0) or 0)
					topic = str(item.get("topic", "") or "")
					content = str(item.get("content", "") or "")
					lines.append(f"- [tick {tick}][{topic}] {content}")
				user_prompt = "\n".join(lines)
				try:
					text = llm.planner_text(
						messages=[
							{"role": "system", "content": "你是记忆压缩器。请把输入记录总结为2-4句，聚焦可执行经验与风险。"},
							{"role": "user", "content": user_prompt},
						],
						temperature=0.2,
						max_tokens=220,
					).strip()
					if text:
						return text
				except Exception as e:
					raise RuntimeError(
						f"mid_term summarize failed: agent_id={str(agent_id or '')} "
						f"input_items={int(len(prep_items))}"
					) from e
		topics = self._top_tags(prep_items, 3)
		return f"阶段记忆摘要：记录{len(prep_items)}条，关键主题：{', '.join(topics) if topics else 'general'}。"

	def _top_tags(self, items: list[dict[str, Any]], max_count: int) -> list[str]:
		counter: dict[str, int] = {}
		for item in items:
			if not isinstance(item, dict):
				continue
			topic = str(item.get("topic", "") or "").strip()
			if not topic:
				continue
			counter[topic] = int(counter.get(topic, 0) or 0) + 1
		sorted_items = sorted(counter.items(), key=lambda x: (-int(x[1]), str(x[0])))
		return [str(k) for k, _ in sorted_items[: int(max_count or 0)]]
