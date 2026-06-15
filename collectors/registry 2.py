"""
collectors/registry.py — rejestr źródeł i auto-discovery.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Type

from .base import Collector


_REGISTRY: dict[str, Type[Collector]] = {}


def register(cls: Type[Collector]) -> Type[Collector]:
    """Dekorator rejestrujący klasę collectora pod jej `source`."""
    if not cls.source:
        raise ValueError(f"Collector {cls.__name__} musi mieć ustawiony source")
    _REGISTRY[cls.source] = cls
    return cls


def discover() -> None:
    """Załaduj wszystkie podmoduły collectors.* — dekoratory @register zarejestrują klasy."""
    import collectors as pkg
    for mod in pkgutil.walk_packages(pkg.__path__, prefix="collectors."):
        if mod.name in ("collectors.base", "collectors.registry",
                        "collectors.__main__", "collectors"):
            continue
        try:
            importlib.import_module(mod.name)
        except Exception as e:
            print(f"[registry] WARN nie udało się załadować {mod.name}: {e}")


def all_collectors() -> dict[str, Type[Collector]]:
    if not _REGISTRY:
        discover()
    return dict(_REGISTRY)


def get_collector(source: str) -> Type[Collector]:
    if not _REGISTRY:
        discover()
    if source not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY.keys())) or "(brak)"
        raise KeyError(f"Brak collectora '{source}'. Dostępne: {available}")
    return _REGISTRY[source]
