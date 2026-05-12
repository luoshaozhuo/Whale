"""Runtime scheduling helpers for ingest."""

from __future__ import annotations

from importlib import import_module

__all__ = ["SourceScheduler"]


def __getattr__(name: str) -> object:
    """Lazily expose runtime helpers without importing the full scheduler tree."""

    if name == "SourceScheduler":
        return import_module("whale.ingest.runtime.scheduler").SourceScheduler
    raise AttributeError(name)
