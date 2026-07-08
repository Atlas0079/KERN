from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from KERN.agent_workflow.full_ws_view_builder import build_full_ws_view
from KERN.agent_workflow.observer import build_agent_perception
from KERN.agent_workflow.view_profile import normalize_workflow_view_profile
from KERN.models.components import ContainerComponent, ContainerSlot, MemoryComponent, ScreenComponent, TagComponent
from KERN.models.entity import Entity
from KERN.models.location import Location
from KERN.models.path import Path as WorldPath
from KERN.models.world_state import WorldState


def _build_world(agent_count: int) -> WorldState:
	ws = WorldState()
	room = Location(location_id="shared_social_room", location_name="Shared Social Room", description="A shared physical room used only for perception-profile inspection.")
	other_room = Location(location_id="other_room", location_name="Other Room", description="A connected room that should disappear in social profile.")
	ws.register_location(room)
	ws.register_location(other_room)
	ws.register_path(WorldPath(path_id="path_shared_other", from_location_id="shared_social_room", to_location_id="other_room"))

	for idx in range(1, max(1, int(agent_count or 1)) + 1):
		agent_id = f"agent_{idx:03d}"
		phone_id = f"phone_{idx:03d}"
		account_id = f"acc_{idx:03d}"

		agent = Entity(entity_id=agent_id, template_id="RumorParticipantAgentBase", entity_name=f"Agent {idx:03d}")
		agent.add_component("TagComponent", TagComponent(tags=["character", "agent", "rumor_participant"]))
		agent.add_component("MemoryComponent", MemoryComponent())
		agent.add_component("ContainerComponent", ContainerComponent(slots={"inventory": ContainerSlot(config={"capacity_count": 4}, items=[])}))
		ws.register_entity(agent)
		room.add_entity_id(agent_id)

		phone = Entity(entity_id=phone_id, template_id="RumorPhoneBase", entity_name=f"Phone {idx:03d}")
		phone.add_component("TagComponent", TagComponent(tags=["device", "phone", "social_media_terminal"]))
		phone.add_component(
			"ScreenComponent",
			ScreenComponent(
				runtime_id="social",
				account_id=account_id,
				app="social_platform",
				view="feed",
				feed_items=[
					{
						"slot": 0,
						"post_id": "post_demo_rumor",
						"author_display_name": "External Rumor Source",
						"summary": "Demo rumor appears in the social feed.",
						"why_visible": "interest_match",
					}
				],
				selected_post_id="post_demo_rumor",
				updated_tick=0,
			),
		)
		ws.register_entity(phone)
		agent.get_component("ContainerComponent").slots["inventory"].items.append(phone_id)
	return ws


def _summarize(perception: dict[str, Any]) -> dict[str, Any]:
	return {
		"visible_entity_ids": [str(x.get("id", "")) for x in list(perception.get("entities", []) or []) if isinstance(x, dict)],
		"visible_entity_count": len(list(perception.get("entities", []) or [])),
		"map_topology_count": len(list(perception.get("map_topology", []) or [])),
		"reachable_location_count": len(list(perception.get("reachable_locations", []) or [])),
		"can_start_conversation_here": bool(perception.get("can_start_conversation_here", False)),
		"inventory_ids": [str(x.get("id", "")) for x in list(perception.get("inventory", []) or []) if isinstance(x, dict)],
		"screen_contexts": [
			{
				"entity_id": str(x.get("entity_id", "")),
				"account_id": str(x.get("account_id", "")),
				"view": str(x.get("view", "")),
				"feed_item_count": len(list(x.get("feed_items", []) or [])),
			}
			for x in list(perception.get("operable_screen_contexts", []) or [])
			if isinstance(x, dict)
		],
	}


def inspect(agent_count: int, actor_id: str, profiles: list[str]) -> dict[str, Any]:
	ws = _build_world(agent_count)
	out: dict[str, Any] = {
		"actor_id": actor_id,
		"agent_count": agent_count,
		"same_location_agent_count": agent_count,
		"profiles": {},
	}
	for profile_id in profiles:
		profile = normalize_workflow_view_profile(profile_id)
		view = build_full_ws_view(ws, actor_id, "inspect_social_perception_profile", {"grounder": True})
		view["workflow_view_profile"] = profile
		perception = build_agent_perception(view, actor_id)
		out["profiles"][profile["profile_id"]] = _summarize(perception)
	return out


def main() -> None:
	parser = argparse.ArgumentParser(description="Inspect workflow view profile effects on same-location social agents.")
	parser.add_argument("--agents", type=int, default=5, help="Number of agents to place in one physical room.")
	parser.add_argument("--actor-id", default="agent_001", help="Actor to inspect.")
	parser.add_argument(
		"--profiles",
		default="embodied_default,social_platform",
		help="Comma-separated workflow view profile ids to compare.",
	)
	parser.add_argument("--output", default="", help="Optional JSON output path.")
	args = parser.parse_args()

	profiles = [x.strip() for x in str(args.profiles or "").split(",") if x.strip()]
	report = inspect(max(1, int(args.agents or 1)), str(args.actor_id or "agent_001"), profiles)
	text = json.dumps(report, ensure_ascii=False, indent=2)
	if args.output:
		out_path = Path(args.output)
		if not out_path.is_absolute():
			out_path = ROOT / out_path
		out_path.parent.mkdir(parents=True, exist_ok=True)
		out_path.write_text(text + "\n", encoding="utf-8")
		print(f"wrote perception profile inspection to {out_path}")
	else:
		print(text)


if __name__ == "__main__":
	main()
