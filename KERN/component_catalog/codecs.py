from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from ..effect_bundle import effect_bundle_from_raw
from ..models.components import ContainerComponent, ContainerSlot, AgentWakePolicyComponent, TaskHostComponent
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
		if raw is None:
			raw = {}
		if not isinstance(raw, dict):
			raise ValueError(f"{self.component_type.__name__} data must be an object")
		data = self.prepare(raw) if self.prepare is not None else dict(raw)
		return self.component_type(**data)

	def serialize(self, component: Any) -> dict[str, Any]:
		raw = serialize_value(component)
		if not isinstance(raw, dict):
			raise TypeError(f"component did not serialize to an object: {self.component_type.__name__}")
		return raw

	def apply_snapshot(self, component: Any, patch: dict[str, Any], *, restore_container_items: bool = True) -> Any:
		data = self.prepare_patch(dict(patch or {})) if self.prepare_patch is not None else dict(patch or {})
		for key, value in data.items():
			if not hasattr(component, key):
				raise ValueError(f"{self.component_type.__name__} has no field: {key}")
			setattr(component, key, value)
		return component
class ContainerCodec:
	def build(self, raw: Any) -> ContainerComponent:
		if raw is None:
			raw = {}
		if not isinstance(raw, dict):
			raise ValueError("ContainerComponent data must be an object")
		data = dict(raw)
		slots_raw = dict(data.get("slots", {}) or {})
		slots: dict[str, ContainerSlot] = {}
		for slot_id, slot_raw in slots_raw.items():
			slot_data = dict(slot_raw or {})
			if "config" in slot_data:
				config = dict(slot_data.get("config") or {})
				items = list(slot_data.get("items", []) or [])
			else:
				config = dict(slot_data)
				items = []
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
		if slots_patch is None:
			return component
		for slot_id, slot_patch in dict(slots_patch).items():
			slot_patch = dict(slot_patch)
			sid = str(slot_id)
			if sid not in component.slots:
				component.slots[sid] = ContainerSlot(config={}, items=[])
			if "config" in slot_patch:
				component.slots[sid].config.update(dict(slot_patch["config"]))
			if restore_container_items and "items" in slot_patch:
				component.slots[sid].items = list(slot_patch["items"])
		return component


def _serialize_wake_policy_rule(rule: Any) -> dict[str, Any]:
	if isinstance(rule, dict):
		return {str(key): serialize_value(value) for key, value in rule.items()}
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
	raise ValueError(f"unsupported wake policy rule: {rule_class}")


class AgentWakePolicyCodec:
	def build(self, raw: Any) -> AgentWakePolicyComponent:
		data = dict(raw or {})
		component = AgentWakePolicyComponent.from_template_data(data)
		if "interrupt_runtime_state" in data:
			component.interrupt_runtime_state = dict(data["interrupt_runtime_state"])
		component._runtime_preset_id = str(data.get("_runtime_preset_id", "") or "")
		return component

	def serialize(self, component: AgentWakePolicyComponent) -> dict[str, Any]:
		rules = [_serialize_wake_policy_rule(rule) for rule in list(component.ruleset or [])]
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
		component: AgentWakePolicyComponent,
		patch: dict[str, Any],
		*,
		restore_container_items: bool = True,
	) -> AgentWakePolicyComponent:
		data = self.serialize(component)
		if "rules" in patch:
			data["rules"] = [dict(item) for item in patch["rules"]]
		for key in ("active_interrupt_preset_id", "_runtime_preset_id"):
			if key in patch:
				data[key] = str(patch.get(key, "") or "")
		for key in ("interrupt_presets", "interrupt_preset_descriptions", "interrupt_runtime_state"):
			if key in patch:
				data[key] = dict(patch[key])
		return self.build(data)


def task_from_dict(raw: dict[str, Any]) -> Task:
	required = (
		"task_id",
		"task_type",
		"target_entity_id",
		"progress",
		"required_progress",
		"multiple_entity",
		"assigned_agent_ids",
		"task_status",
		"parameters",
		"progressor_id",
		"progressor_params",
		"start_bundle",
		"tick_bundle",
		"cleanup_bundle",
		"completion_bundle",
	)
	missing = [key for key in required if key not in raw]
	if missing:
		raise ValueError(f"task data missing fields: {', '.join(missing)}")
	task = Task(task_id=str(raw["task_id"]), task_type=str(raw["task_type"]))
	task.action_type = str(raw.get("action_type", task.action_type) or task.action_type)
	task.target_entity_id = str(raw["target_entity_id"])
	task.progress = float(raw["progress"])
	task.required_progress = float(raw["required_progress"])
	task.multiple_entity = bool(raw["multiple_entity"])
	task.assigned_agent_ids = [str(item) for item in raw["assigned_agent_ids"]]
	task.task_status = str(raw["task_status"])
	task.parameters = dict(raw["parameters"])
	task.progressor_id = str(raw["progressor_id"])
	progressor_params = dict(raw["progressor_params"])
	if "progress_contributors" in progressor_params:
		raise ValueError("task progressor_params.progress_contributors is removed; use add_terms/mul_terms")
	task.progressor_params = progressor_params
	task.start_bundle = effect_bundle_from_raw(raw["start_bundle"])
	task.tick_bundle = effect_bundle_from_raw(raw["tick_bundle"])
	task.cleanup_bundle = effect_bundle_from_raw(raw["cleanup_bundle"])
	task.completion_bundle = effect_bundle_from_raw(raw["completion_bundle"])
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
		if raw is None:
			raw = {}
		if not isinstance(raw, dict):
			raise ValueError("TaskHostComponent data must be an object")
		component = TaskHostComponent()
		for task_id, task_raw in dict(raw.get("tasks", {}) or {}).items():
			payload = dict(task_raw)
			if "task_id" not in payload:
				raise ValueError(f"task data missing task_id: {task_id}")
			task = task_from_dict(payload)
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
		if "tasks" in patch:
			component.tasks = self.build({"tasks": patch["tasks"]}).tasks
		return component


__all__ = ["AgentWakePolicyCodec", "ContainerCodec", "DataclassCodec", "TaskHostCodec"]
