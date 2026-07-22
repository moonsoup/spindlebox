"""Pluggable output-language backends. Adding a language = one module + one register call."""

from __future__ import annotations

from spindlebox.generate.base import GeneratedFile, GeneratorBackend, GenOptions
from spindlebox.generate.rust_backend import RustBackend

BACKENDS: dict[str, type[GeneratorBackend]] = {}


def register_backend(cls: type[GeneratorBackend]) -> None:
    BACKENDS[cls.name] = cls


register_backend(RustBackend)

__all__ = ["BACKENDS", "GeneratedFile", "GenOptions", "GeneratorBackend", "register_backend"]
