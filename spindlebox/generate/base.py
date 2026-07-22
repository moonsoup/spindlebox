"""Generator backend interface: index in, skeleton files out."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from spindlebox.schema import ScaIndex


@dataclass
class GeneratedFile:
    relpath: str
    content: str


@dataclass
class GenOptions:
    group: str | None = None  # restrict generation to one group path


class GeneratorBackend(ABC):
    name: str = "?"

    @abstractmethod
    def generate(self, index: ScaIndex, options: GenOptions) -> list[GeneratedFile]:
        ...
