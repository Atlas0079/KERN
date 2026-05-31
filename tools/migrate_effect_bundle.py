from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _convert_dynamic_output(node: dict[str, Any]) -> dict[str, Any]:
	dyn = node.get("dynamic_outputs_from_component", {}) or {}
	component = str(dyn.get("component", "") or "").strip()
	property_name = str(dyn.get("property", "") or "").strip()
	if component == "EdibleComponent" and property_name == "effects_on_consume":
		return {
			"effect": "InvokeBundle",
			"target": "target",
			"component": "EdibleComponent",
			"property": "on_consume_bundle",
		}
	raise ValueError(f"unsupported dynamic_outputs_from_component: {component}.{property_name}")


def _ensure_bundle_from_effects(effects: Any, where: str) -> dict[str, Any]:
	if not isinstance(effects, list):
		raise ValueError(f"{where} must be list")
	return {"effects": [item for item in effects if isinstance(item, dict)]}


def _transform_node(node: Any, where: str = "root") -> Any:
	if isinstance(node, list):
		return [_transform_node(item, f"{where}[{idx}]") for idx, item in enumerate(node)]
	if not isinstance(node, dict):
		return node

	if "dynamic_outputs_from_component" in node:
		return _convert_dynamic_output(node)

	out: dict[str, Any] = {}
	for key, value in node.items():
		out[str(key)] = _transform_node(value, f"{where}.{key}")

	if "outputs" in out:
		if "bundle" in out:
			raise ValueError(f"{where} cannot contain both outputs and bundle")
		out["bundle"] = _ensure_bundle_from_effects(out.pop("outputs"), f"{where}.outputs")

	if "effects" in out and "on_event" in out:
		if "bundle" in out:
			raise ValueError(f"{where} reaction rule cannot contain both effects and bundle")
		out["bundle"] = _ensure_bundle_from_effects(out.pop("effects"), f"{where}.effects")

	if "tick_effects" in out:
		if "tick_bundle" in out:
			raise ValueError(f"{where} cannot contain both tick_effects and tick_bundle")
		out["tick_bundle"] = _ensure_bundle_from_effects(out.pop("tick_effects"), f"{where}.tick_effects")

	if "completion_effects" in out:
		if "completion_bundle" in out:
			raise ValueError(f"{where} cannot contain both completion_effects and completion_bundle")
		out["completion_bundle"] = _ensure_bundle_from_effects(out.pop("completion_effects"), f"{where}.completion_effects")

	if "effects_on_consume" in out:
		if "on_consume_bundle" in out:
			raise ValueError(f"{where} cannot contain both effects_on_consume and on_consume_bundle")
		out["on_consume_bundle"] = _ensure_bundle_from_effects(out.pop("effects_on_consume"), f"{where}.effects_on_consume")

	return out


def _write_json(path: Path, data: Any) -> None:
	text = json.dumps(data, ensure_ascii=False, indent=4)
	path.write_text(text + "\n", encoding="utf-8")


def main() -> None:
	project_root = Path(__file__).resolve().parents[1]
	data_root = project_root / "Data"
	if not data_root.exists():
		raise FileNotFoundError(f"Data directory not found: {data_root}")

	changed: list[Path] = []
	for path in sorted(data_root.rglob("*.json")):
		original = json.loads(path.read_text(encoding="utf-8"))
		updated = _transform_node(original, where=str(path.relative_to(project_root)))
		if updated != original:
			_write_json(path, updated)
			changed.append(path.relative_to(project_root))

	print(json.dumps({"changed_files": [str(p) for p in changed], "count": len(changed)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
	main()
