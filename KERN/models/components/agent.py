from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentSetting:
	agent_name: str = ""
	personality_summary: str = ""
	common_knowledge_summary: str = ""
	money: float = 0.0
