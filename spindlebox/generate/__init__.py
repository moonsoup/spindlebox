"""Pluggable output-language backends.

Adding an output language = one emit profile (generate/emit_profiles/<lang>.json),
consumed by the generic engine in profile_backend.py. Hand-written backend modules
remain supported via register_backend and take precedence over a same-named profile
(the legacy RustBackend stays authoritative for 'rust'; its emit profile is held
byte-identical to it by differential test).
"""

from __future__ import annotations

from spindlebox.generate.base import GeneratedFile, GeneratorBackend, GenOptions
from spindlebox.generate.rust_backend import RustBackend

BACKENDS: dict[str, type[GeneratorBackend]] = {}


def register_backend(cls: type[GeneratorBackend]) -> None:
    BACKENDS[cls.name] = cls


register_backend(RustBackend)

from spindlebox.generate.profile_backend import load_emit_backends  # noqa: E402

for _lang, _cls in load_emit_backends().items():
    if _lang not in BACKENDS:
        register_backend(_cls)

__all__ = ["BACKENDS", "GeneratedFile", "GenOptions", "GeneratorBackend", "register_backend"]
