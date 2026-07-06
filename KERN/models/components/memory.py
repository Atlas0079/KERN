from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryComponent:
	short_term_queue: list[dict[str, Any]] = field(default_factory=list)
	short_term_max_entries: int = 30
	mid_term_prep_queue: list[dict[str, Any]] = field(default_factory=list)
	mid_term_prep_max_entries: int = 50
	mid_term_queue: list[dict[str, Any]] = field(default_factory=list)
	mid_term_max_entries: int = 20
	last_mid_term_summary_tick: int = -1
	mid_term_summary_cooldown_ticks: int = 15
	last_event_seq_seen: int = 0
	last_interaction_seq_seen: int = 0

	def _normalize_importance(self, value: float) -> float:
		try:
			v = float(value)
		except Exception:
			v = 0.5
		if v < 0:
			return 0.0
		if v > 1:
			return 1.0
		return v

	def _normalize_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
		tick = int(entry.get("tick", 0) or 0)
		content = str(entry.get("content", entry.get("text", "")) or "").strip()
		if not content:
			return {}
		time_str = str(entry.get("time_str", "") or "")
		entry_type = str(entry.get("type", "observation") or "observation")
		topic = str(entry.get("topic", "") or "")
		importance = self._normalize_importance(float(entry.get("importance", 0.5) or 0.5))
		location_id = str(entry.get("location_id", "") or "")
		actor_id = str(entry.get("actor_id", "") or "")
		target_id = str(entry.get("target_id", "") or "")
		tags_raw = entry.get("tags", []) or []
		tags = [str(x) for x in list(tags_raw)] if isinstance(tags_raw, list) else []
		decay_rate = self._normalize_importance(float(entry.get("decay_rate", 0.08 if importance < 0.2 else 0.02) or 0.0))
		current_weight = self._normalize_importance(float(entry.get("current_weight", importance) or 0.0))
		created_tick = int(entry.get("created_tick", tick) or tick)
		last_accessed_tick = int(entry.get("last_accessed_tick", tick) or tick)
		out = {
			"tick": tick,
			"time_str": time_str,
			"type": entry_type,
			"topic": topic,
			"importance": importance,
			"current_weight": current_weight,
			"decay_rate": decay_rate,
			"created_tick": created_tick,
			"last_accessed_tick": last_accessed_tick,
			"location_id": location_id,
			"actor_id": actor_id,
			"target_id": target_id,
			"content": content,
			"tags": tags,
		}
		if isinstance(entry.get("source", None), dict):
			out["source"] = dict(entry.get("source") or {})
		return out

	def _entry_score(self, entry: dict[str, Any], current_tick: int) -> float:
		try:
			weight = float(entry.get("current_weight", entry.get("importance", 0.5)) or 0.0)
		except Exception:
			weight = 0.5
		try:
			decay = float(entry.get("decay_rate", 0.02) or 0.02)
		except Exception:
			decay = 0.02
		age = max(0, int(current_tick or 0) - int(entry.get("last_accessed_tick", entry.get("tick", 0)) or 0))
		return weight - decay * age

	def prune_to_tick(self, current_tick: int) -> None:
		min_score = 0.05
		kept: list[dict[str, Any]] = []
		for entry in list(self.short_term_queue or []):
			if not isinstance(entry, dict):
				continue
			score = self._entry_score(entry, current_tick)
			if score < min_score:
				continue
			entry["current_weight"] = self._normalize_importance(score)
			kept.append(entry)
		self.short_term_queue = kept

	def per_tick(self, ws: Any, _entity_id: str, _ticks_per_minute: int) -> None:
		tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0) or 0)
		self.prune_to_tick(tick)

	def add_short_term(self, entry: dict[str, Any]) -> None:
		norm = self._normalize_entry(entry if isinstance(entry, dict) else {})
		if not norm:
			return
		self.short_term_queue.append(norm)
		self.prune_to_tick(int(norm.get("tick", 0) or 0))
		limit = int(self.short_term_max_entries or 0)
		while limit > 0 and len(self.short_term_queue) > limit:
			scored = [
				(self._entry_score(item, int(norm.get("tick", 0) or 0)), idx, item)
				for idx, item in enumerate(list(self.short_term_queue or []))
				if isinstance(item, dict)
			]
			if not scored:
				break
			_score, idx, evicted = min(scored, key=lambda x: (float(x[0]), int(x[1])))
			self.short_term_queue.pop(idx)
			if float(evicted.get("importance", 0.0) or 0.0) >= 0.45:
				self.add_mid_term_prep(evicted)

	def add_mid_term_prep(self, entry: dict[str, Any]) -> None:
		norm = self._normalize_entry(entry if isinstance(entry, dict) else {})
		if not norm:
			return
		self.mid_term_prep_queue.append(norm)
		limit = int(self.mid_term_prep_max_entries or 0)
		if limit > 0 and len(self.mid_term_prep_queue) > limit:
			self.mid_term_prep_queue = self.mid_term_prep_queue[-limit:]

	def should_summarize_mid_term(self, current_tick: int) -> bool:
		if len(self.mid_term_prep_queue) < int(self.mid_term_prep_max_entries or 0):
			return False
		now = int(current_tick or 0)
		last = int(self.last_mid_term_summary_tick or -1)
		return (now - last) >= int(self.mid_term_summary_cooldown_ticks or 0)

	def add_mid_term_summary(self, summary_text: str, tick_start: int, tick_end: int, tags: list[str] | None = None) -> None:
		text = str(summary_text or "").strip()
		if not text:
			return
		rec = {
			"tick_start": int(tick_start or 0),
			"tick_end": int(tick_end or 0),
			"summary": text,
			"tags": [str(x) for x in list(tags or [])],
		}
		self.mid_term_queue.append(rec)
		limit = int(self.mid_term_max_entries or 0)
		if limit > 0 and len(self.mid_term_queue) > limit:
			self.mid_term_queue = self.mid_term_queue[-limit:]
		self.last_mid_term_summary_tick = int(tick_end or 0)

	def add_entry(self, text: str, tick: int, importance: float = 0.5, tags: list[str] | None = None) -> None:
		self.add_short_term(
			{
				"tick": int(tick),
				"time_str": "",
				"type": "note",
				"topic": "",
				"importance": self._normalize_importance(importance),
				"location_id": "",
				"actor_id": "",
				"target_id": "",
				"content": str(text or ""),
				"tags": [str(x) for x in list(tags or [])],
			}
		)

	def short_term_text(self, max_items: int = 10) -> str:
		items = list(self.short_term_queue or [])
		if not items:
			return ""
		items = items[-int(max_items or 10) :]
		lines: list[str] = []
		for e in items:
			if not isinstance(e, dict):
				continue
			content = str(e.get("content", "") or "").strip()
			if not content:
				continue
			tick = int(e.get("tick", 0) or 0)
			imp = float(e.get("importance", 0.5) or 0.5)
			topic = str(e.get("topic", "") or "")
			topic_text = f"[{topic}] " if topic else ""
			lines.append(f"- [tick {tick}][imp {imp:.2f}] {topic_text}{content}")
		return "\n".join(lines)

	def to_summary_text(self, max_items: int = 4) -> str:
		items = list(self.mid_term_queue or [])
		if not items:
			return ""
		items = items[-int(max_items or 4) :]
		lines: list[str] = []
		for e in items:
			if not isinstance(e, dict):
				continue
			txt = str(e.get("summary", "") or "").strip()
			if not txt:
				continue
			t0 = int(e.get("tick_start", 0) or 0)
			t1 = int(e.get("tick_end", 0) or 0)
			lines.append(f"- [tick {t0}-{t1}] {txt}")
		return "\n".join(lines)
