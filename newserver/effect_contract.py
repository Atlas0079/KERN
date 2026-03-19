from __future__ import annotations

EFFECT_TYPES = frozenset(
	{
		"AgentControlTick",
		"WorkerTick",
		"ModifyProperty",
		"AddTag",
		"RemoveTag",
		"ApplyMetaAction",
		"AttachInterruptPresetDetails",
		"CreateEntity",
		"DestroyEntity",
		"MoveEntity",
		"AddCondition",
		"RemoveCondition",
		"ConsumeInputs",
		"CreateTask",
		"AcceptTask",
		"ProgressTask",
		"UpdateTaskStatus",
		"FinishTask",
		"KillEntity",
		"StartConversation",
		"SetCooldown",
		"AddMemoryNote",
		"EmitEvent",
	}
)


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
