"""
memory/__init__.py — JARVIS Memory Subsystem.

Re-exports MemoryManager as the primary public interface.
All external code should import from here or from memory.manager directly.
"""
from memory.manager import MemoryManager

__all__ = ["MemoryManager"]
