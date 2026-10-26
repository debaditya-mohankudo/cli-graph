"""Verb registry and group discovery."""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable

MODES = ("read", "write")


@dataclass(frozen=True)
class Verb:
    area: str
    name: str
    mode: str
    desc: str
    handler: Callable
    configure: Callable | None


class Registry:
    def __init__(self):
        self._verbs = {}

    def verb(self, area, name, *, mode, desc, args=None):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

        def register(handler):
            if (area, name) in self._verbs:
                raise ValueError(f"duplicate verb: {area} {name}")
            self._verbs[(area, name)] = Verb(area, name, mode, desc, handler, args)
            return handler

        return register

    def areas(self):
        return sorted({area for area, _ in self._verbs})

    def verbs(self, area):
        return sorted((v for (a, _), v in self._verbs.items() if a == area), key=lambda v: v.name)

    def get(self, area, name):
        return self._verbs.get((area, name))


def load_groups(registry, package="mac.groups"):
    """Import every module in `package` and call its register(registry)."""
    pkg = importlib.import_module(package)
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        if not hasattr(module, "register"):
            raise RuntimeError(f"{module.__name__} has no register(registry)")
        module.register(registry)
