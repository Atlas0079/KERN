"""Concrete external runtime adapters bundled with KERN."""

from .empty import EmptyExternalRuntime
from .social_platform import SQLiteSocialPlatform

__all__ = ["EmptyExternalRuntime", "SQLiteSocialPlatform"]
