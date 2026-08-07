from __future__ import annotations

from typing import Any

from KERN.external_runtime_catalog import ExternalRuntimeSpec
from KERN.external_runtimes import EmptyExternalRuntime
from KERN.package_definitions import package_external_runtime


def _create_empty_social_platform(context: dict[str, Any], options: dict[str, Any]) -> EmptyExternalRuntime:
	return EmptyExternalRuntime(runtime_id=str(context["runtime_id"]), options=dict(options))


@package_external_runtime(
	ExternalRuntimeSpec(
		provider_id="social_propagation:empty_platform",
		factory=_create_empty_social_platform,
	)
)
def empty_social_platform_runtime() -> None:
	pass
