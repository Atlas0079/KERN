"""
Task progressors.

Progressor is responsible for "algorithm"; Task/Recipe is responsible for "parameters".
"""

from .base import Progressor
from .registry import get_progressor, register_progressor
from .linear import LinearProgressor

# Default registration
register_progressor(LinearProgressor())

__all__ = [
	"Progressor",
	"get_progressor",
	"register_progressor",
	"LinearProgressor",
]

