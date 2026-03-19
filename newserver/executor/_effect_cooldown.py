from __future__ import annotations

from typing import Any

from ..models.components import CooldownComponent


def execute_set_cooldown(executor: Any, ws: Any, data: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
	target_key = data.get("target", "self")
	target = executor._resolve_entity_from_ctx(ws, context, str(target_key))
	if target is None:
		return [{"type": "ExecutorError", "message": "SetCooldown: target missing"}]
	
	comp = target.get_component("CooldownComponent")
	if comp is None:
		# Auto-add if missing, to simplify entity templates
		comp = CooldownComponent()
		target.add_component("CooldownComponent", comp)
	
	key = str(data.get("key", "") or "")
	if not key:
		return [{"type": "ExecutorError", "message": "SetCooldown: key missing"}]
	
	current_tick = int(getattr(getattr(ws, "game_time", None), "total_ticks", 0))
	comp.set_cooldown(key, current_tick)
	
	return [{"type": "CooldownSet", "entity_id": target.entity_id, "key": key, "tick": current_tick}]
