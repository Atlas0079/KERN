from __future__ import annotations

EFFECT_SPECS: dict[str, dict[str, str]] = {
	"AgentControlTick": {"binder": "_bind_agent_control_tick", "handler": "_execute_agent_control_tick"},
	"WorkerTick": {"binder": "_bind_worker_tick", "handler": "_execute_worker_tick"},
	"StatusTick": {"binder": "_bind_status_tick", "handler": "_execute_status_tick"},
	"ModifyProperty": {"binder": "_bind_modify_property", "handler": "_execute_modify_property"},
	"AddTag": {"binder": "_bind_add_tag", "handler": "_execute_add_tag"},
	"RemoveTag": {"binder": "_bind_remove_tag", "handler": "_execute_remove_tag"},
	"ApplyMetaAction": {"binder": "_bind_apply_meta_action", "handler": "_execute_apply_meta_action"},
	"AttachDetails": {"binder": "_bind_attach_details", "handler": "_execute_attach_details"},
	"CreateEntity": {"binder": "_bind_create_entity", "handler": "_execute_create_entity"},
	"DestroyEntity": {"binder": "_bind_destroy_entity", "handler": "_execute_destroy_entity"},
	"MoveEntity": {"binder": "_bind_move_entity", "handler": "_execute_move_entity"},
	"AddStatus": {"binder": "_bind_add_status", "handler": "_execute_add_status"},
	"RemoveStatus": {"binder": "_bind_remove_status", "handler": "_execute_remove_status"},
	"ConsumeInputs": {"binder": "_bind_consume_inputs", "handler": "_execute_consume_inputs"},
	"CreateTask": {"binder": "_bind_create_task", "handler": "_execute_create_task"},
	"AcceptTask": {"binder": "_bind_accept_task", "handler": "_execute_accept_task"},
	"ProgressTask": {"binder": "_bind_progress_task", "handler": "_execute_progress_task"},
	"UpdateTaskStatus": {"binder": "_bind_update_task_status", "handler": "_execute_update_task_status"},
	"FinishTask": {"binder": "_bind_finish_task", "handler": "_execute_finish_task"},
	"KillEntity": {"binder": "_bind_kill_entity", "handler": "_execute_kill_entity"},
	"StartConversation": {"binder": "_bind_start_conversation", "handler": "_execute_start_conversation"},
	"AddMemoryNote": {"binder": "_bind_add_memory_note", "handler": "_execute_add_memory_note"},
	"EmitEvent": {"binder": "_bind_emit_event", "handler": "_execute_emit_event"},
	"ExchangeResources": {"binder": "_bind_exchange_resources", "handler": "_execute_exchange_resources"},
	"AbortSimulation": {"binder": "_bind_abort_simulation", "handler": "_execute_abort_simulation"},
}

EFFECT_TYPES = frozenset(EFFECT_SPECS.keys())


def diff_effect_types(actual: set[str] | frozenset[str], expected: set[str] | frozenset[str], actual_name: str) -> list[str]:
	actual_set = {str(x) for x in set(actual or set()) if str(x)}
	expected_set = {str(x) for x in set(expected or set()) if str(x)}
	missing = sorted(expected_set - actual_set)
	extra = sorted(actual_set - expected_set)
	out: list[str] = []
	if missing:
		out.append(f"{actual_name} missing effect types: {missing}")
	if extra:
		out.append(f"{actual_name} has unknown effect types: {extra}")
	return out
