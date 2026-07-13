from __future__ import annotations

from .catalog import EffectCatalog
from .spec import EffectSpec


CORE_EFFECT_MODULES: tuple[tuple[str, str], ...] = (
	("InvokeBundle", "KERN.executor._effect_bundle"),
	("RandomBundle", "KERN.executor._effect_random_bundle"),
	("ApplyToQuery", "KERN.executor._effect_query"),
	("AgentControlTick", "KERN.executor._effect_agent"),
	("WorkerTick", "KERN.executor._effect_agent"),
	("StatusTick", "KERN.executor._effect_task"),
	("ModifyProperty", "KERN.executor._effect_property"),
	("AddTag", "KERN.executor._effect_property"),
	("RemoveTag", "KERN.executor._effect_property"),
	("ApplyMetaAction", "KERN.executor._effect_agent"),
	("AttachDetails", "KERN.executor._effect_agent"),
	("CreateEntity", "KERN.executor._effect_entity"),
	("DestroyEntity", "KERN.executor._effect_entity"),
	("MoveEntity", "KERN.executor._effect_entity"),
	("AddStatus", "KERN.executor._effect_task"),
	("RemoveStatus", "KERN.executor._effect_task"),
	("ConsumeInputs", "KERN.executor._effect_task"),
	("CreateTask", "KERN.executor._effect_task"),
	("AcceptTask", "KERN.executor._effect_task"),
	("ProgressTask", "KERN.executor._effect_task"),
	("UpdateTaskStatus", "KERN.executor._effect_task"),
	("FinishTask", "KERN.executor._effect_task"),
	("InterruptCurrentTask", "KERN.executor._effect_task"),
	("InterruptTask", "KERN.executor._effect_task"),
	("ResumeTask", "KERN.executor._effect_task"),
	("CancelTask", "KERN.executor._effect_task"),
	("KillEntity", "KERN.executor._effect_entity"),
	("StartConversation", "KERN.executor._effect_conversation"),
	("AddMemoryNote", "KERN.executor._effect_memory"),
	("ApplyMemoryPatch", "KERN.executor._effect_memory"),
	("EmitEvent", "KERN.executor._effect_event"),
	("ExchangeResources", "KERN.executor._effect_resource"),
	("AbortSimulation", "KERN.executor._effect_resource"),
	("SetEnvironmentField", "KERN.executor._effect_environment"),
	("AddEnvironmentCondition", "KERN.executor._effect_environment"),
	("RemoveEnvironmentCondition", "KERN.executor._effect_environment"),
	("EnvironmentConditionTick", "KERN.executor._effect_environment"),
	("ObserveSocialFeed", "KERN.executor._effect_social_platform"),
	("ObserveSocialPost", "KERN.executor._effect_social_platform"),
	("CreateSocialPost", "KERN.executor._effect_social_platform"),
	("InteractSocialPost", "KERN.executor._effect_social_platform"),
	("FollowSocialAccount", "KERN.executor._effect_social_platform"),
	("SocialActivityGateTick", "KERN.executor._effect_social_activity"),
)


def build_core_effect_catalog() -> EffectCatalog:
	catalog = EffectCatalog()
	for effect_id, module in CORE_EFFECT_MODULES:
		catalog.register(EffectSpec(effect_id=effect_id, module=module))
	return catalog
