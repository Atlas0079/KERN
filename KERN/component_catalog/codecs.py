from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from ..effect_bundle import effect_bundle_from_raw
from ..models.components import ContainerComponent, ContainerSlot, DecisionArbiterComponent, TaskHostComponent
from ..models.task import Task


def serialize_value(value: Any) -> Any:
	if value is None or isinstance(value, (str, int, float, bool)):
		return value
	if isinstance(value, dict):
		return {str(key): serialize_value(item) for key, item in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [serialize_value(item) for item in value]
	if is_dataclass(value):
		return serialize_value(asdict(value))
	if hasattr(value, "__dict__"):
		return serialize_value(dict(vars(value)))
	return str(value)


class DataclassCodec:
	def __init__(
		self,
		component_type: type,
		prepare: Callable[[Any], dict[str, Any]] | None = None,
		prepare_patch: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
	) -> None:
		if not isinstance(component_type, type) or not is_dataclass(component_type):
			raise TypeError(f"DataclassCodec requires a dataclass type: {component_type!r}")
		self.component_type = component_type
		self.prepare = prepare
		self.prepare_patch = prepare_patch

	def build(self, raw: Any) -> Any:
		data = self.prepare(raw) if self.prepare is not None else dict(raw or {}) if isinstance(raw, dict) else {}
		return self.component_type(**data)

	def serialize(self, component: Any) -> dict[str, Any]:
		raw = serialize_value(component)
		if not isinstance(raw, dict):
			raise TypeError(f"component did not serialize to an object: {self.component_type.__name__}")
		return raw

	def apply_snapshot(self, component: Any, patch: dict[str, Any], *, restore_container_items: bool = True) -> Any:
		data = self.prepare_patch(dict(patch or {})) if self.prepare_patch is not None else dict(patch or {})
		for key, value in data.items():
			if hasattr(component, key):
				setattr(component, key, value)
		return component


class ContainerCodec:
	def build(self, raw: Any) -> ContainerComponent:
		data = dict(raw or {}) if isinstance(raw, dict) else {}
		slots_raw = data.get("slots", {}) or {}
		slots: dict[str, ContainerSlot] = {}
		if isinstance(slots_raw, dict):
			for slot_id, slot_raw in slots_raw.items():
				slot_data = dict(slot_raw or {}) if isinstance(slot_raw, dict) else {}
				if isinstance(slot_data.get("config"), dict):
					config = dict(slot_data.get("config") or {})
					items = [str(item) for item in list(slot_data.get("items", []) or [])]
				else:
					config = dict(slot_data)
					items = []
				config.setdefault("capacity_volume", 999.0)
				config.setdefault("capacity_count", 999)
				config.setdefault("accepted_tags", [])
				config.setdefault("transparent", False)
				slots[str(slot_id)] = ContainerSlot(config=config, items=items)
		return ContainerComponent(slots=slots)

	def serialize(self, component: ContainerComponent) -> dict[str, Any]:
		return {
			"slots": {
				str(slot_id): {
					"config": serialize_value(dict(slot.config or {})),
					"items": [str(item) for item in list(slot.items or [])],
				}
				for slot_id, slot in dict(component.slots or {}).items()
			}
		}

	def apply_snapshot(
		self,
		component: ContainerComponent,
		patch: dict[str, Any],
		*,
		restore_container_items: bool = True,
	) -> ContainerComponent:
		slots_patch = patch.get("slots", None)
		if not isinstance(slots_patch, dict):
			return component
		for slot_id, slot_patch in slots_patch.items():
			if not isinstance(slot_patch, dict):
				continue
			sid = str(slot_id)
			if sid not in component.slots:
				component.slots[sid] = ContainerSlot(config={}, items=[])
			if isinstance(slot_patch.get("config"), dict):
				component.slots[sid].config.update(dict(slot_patch.get("config") or {}))
			if restore_container_items and isinstance(slot_patch.get("items"), list):
				component.slots[sid].items = [str(item) for item in list(slot_patch.get("items") or [])]
		return component


def _serialize_arbiter_rule(rule: Any) -> dict[str, Any] | None:
	if isinstance(rule, dict):
		rule_type = str(rule.get("type", "") or "").strip()
		return {str(key): serialize_value(value) for key, value in rule.items()} if rule_type else None
	rule_class = str(getattr(getattr(rule, "__class__", None), "__name__", "") or "")
	priority = int(getattr(rule, "priority", 999) or 999)
	if rule_class == "LowNutritionRule":
		return {"type": "LowNutrition", "priority": priority, "threshold": float(getattr(rule, "threshold", 50.0) or 50.0)}
	if rule_class == "PerceptionChangeRule":
		return {
			"type": "PerceptionChange",
			"priority": priority,
			"trigger_on_agent_sighted": bool(getattr(rule, "trigger_on_agent_sighted", True)),
			"trigger_on_agent_left": bool(getattr(rule, "trigger_on_agent_left", True)),
		}
	if rule_class == "CorpseSightedRule":
		return {"type": "CorpseSighted", "priority": priority, "trigger_on_new_corpse": bool(getattr(rule, "trigger_on_new_corpse", True))}
	if rule_class == "NoActiveTaskRule":
		return {"type": "NoActiveTask", "priority": priority}
	return None


class DecisionArbiterCodec:
	def build(self, raw: Any) -> DecisionArbiterComponent:
		data = dict(raw or {}) if isinstance(raw, dict) else {}
		component = DecisionArbiterComponent.from_template_data(data)
		if isinstance(data.get("interrupt_runtime_state"), dict):
			component.interrupt_runtime_state = dict(data.get("interrupt_runtime_state") or {})
		component._runtime_preset_id = str(data.get("_runtime_preset_id", "") or "")
		return component

	def serialize(self, component: DecisionArbiterComponent) -> dict[str, Any]:
		rules = [serialized for rule in list(component.ruleset or []) if (serialized := _serialize_arbiter_rule(rule)) is not None]
		return {
			"rules": rules,
			"active_interrupt_preset_id": str(component.active_interrupt_preset_id or ""),
			"interrupt_presets": serialize_value(dict(component.interrupt_presets or {})),
			"interrupt_preset_descriptions": serialize_value(dict(component.interrupt_preset_descriptions or {})),
			"interrupt_runtime_state": serialize_value(dict(component.interrupt_runtime_state or {})),
			"_runtime_preset_id": str(component._runtime_preset_id or ""),
		}

	def apply_snapshot(
		self,
		component: DecisionArbiterComponent,
		patch: dict[str, Any],
		*,
		restore_container_items: bool = True,
	) -> DecisionArbiterComponent:
		data = self.serialize(component)
		if isinstance(patch.get("rules", patch.get("ruleset")), list):
			data["rules"] = [dict(item) for item in list(patch.get("rules", patch.get("ruleset")) or []) if isinstance(item, dict)]
		for key in ("active_interrupt_preset_id", "_runtime_preset_id"):
			if key in patch:
				data[key] = str(patch.get(key, "") or "")
		for key in ("interrupt_presets", "interrupt_preset_descriptions", "interrupt_runtime_state"):
			if isinstance(patch.get(key), dict):
				data[key] = dict(patch.get(key) or {})
		return self.build(data)


def task_from_dict(raw: dict[str, Any]) -> Task:
	task = Task(task_id=str(raw.get("task_id", "") or ""), task_type=str(raw.get("task_type", "") or ""))
	task.action_type = str(raw.get("action_type", task.action_type) or task.action_type)
	task.target_entity_id = str(raw.get("target_entity_id", "") or "")
	task.progress = float(raw.get("progress", 0.0) or 0.0)
	task.required_progress = float(raw.get("required_progress", task.required_progress) or task.required_progress)
	task.multiple_entity = bool(raw.get("multiple_entity", False))
	assigned = raw.get("assigned_agent_ids", []) or []
	if isinstance(assigned, list):
		task.assigned_agent_ids = [str(item) for item in assigned]
	task.task_status = str(raw.get("task_status", task.task_status) or task.task_status)
	if isinstance(raw.get("parameters"), dict):
		task.parameters = dict(raw.get("parameters") or {})
	task.progressor_id = str(raw.get("progressor_id", "") or "")
	progressor_params = raw.get("progressor_params", {}) or {}
	if isinstance(progressor_params, dict):
		if "progress_contributors" in progressor_params:
			raise ValueError("task progressor_params.progress_contributors is removed; use add_terms/mul_terms")
		task.progressor_params = dict(progressor_params)
	task.start_bundle = effect_bundle_from_raw(raw.get("start_bundle", {}) or {"effects": []})
	task.tick_bundle = effect_bundle_from_raw(raw.get("tick_bundle", {}) or {"effects": []})
	task.cleanup_bundle = effect_bundle_from_raw(raw.get("cleanup_bundle", {}) or {"effects": []})
	task.completion_bundle = effect_bundle_from_raw(raw.get("completion_bundle", {}) or {"effects": []})
	return task


def serialize_task(task: Task) -> dict[str, Any]:
	return {
		"task_id": str(task.task_id or ""),
		"task_type": str(task.task_type or ""),
		"action_type": str(task.action_type or "Action"),
		"target_entity_id": str(task.target_entity_id or ""),
		"progress": float(task.progress or 0.0),
		"required_progress": float(task.required_progress or 0.0),
		"multiple_entity": bool(task.multiple_entity),
		"assigned_agent_ids": [str(item) for item in list(task.assigned_agent_ids or [])],
		"task_status": str(task.task_status or "Inactive"),
		"parameters": serialize_value(dict(task.parameters or {})),
		"progressor_id": str(task.progressor_id or ""),
		"progressor_params": serialize_value(dict(task.progressor_params or {})),
		"start_bundle": serialize_value(task.start_bundle),
		"tick_bundle": serialize_value(task.tick_bundle),
		"cleanup_bundle": serialize_value(task.cleanup_bundle),
		"completion_bundle": serialize_value(task.completion_bundle),
	}


class TaskHostCodec:
	def build(self, raw: Any) -> TaskHostComponent:
		component = TaskHostComponent()
		tasks_raw = (raw or {}).get("tasks", {}) if isinstance(raw, dict) else {}
		if isinstance(tasks_raw, dict):
			for task_id, task_raw in tasks_raw.items():
				payload = dict(task_raw) if isinstance(task_raw, dict) else {}
				payload.setdefault("task_id", str(task_id))
				task = task_from_dict(payload)
				if task.task_id:
					component.tasks[task.task_id] = task
		return component

	def serialize(self, component: TaskHostComponent) -> dict[str, Any]:
		return {"tasks": {str(task.task_id): serialize_task(task) for task in component.get_all_tasks() if str(task.task_id)}}

	def apply_snapshot(
		self,
		component: TaskHostComponent,
		patch: dict[str, Any],
		*,
		restore_container_items: bool = True,
	) -> TaskHostComponent:
		if isinstance(patch.get("tasks"), dict):
			component.tasks = self.build({"tasks": patch.get("tasks")}).tasks
		return component
