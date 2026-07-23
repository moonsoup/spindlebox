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
    # spindles are long and spindly: one item, one line. --pretty expands
    # bodies onto multiple lines for human editing.
    pretty: bool = False


def flatten_block(block: list[str]) -> list[str]:
    """Collapse a multi-line code block into one spindle line.

    The first line keeps its indentation; the rest are stripped and joined
    with single spaces. Blank lines inside the block vanish.
    """
    if not block:
        return block
    rest = " ".join(line.strip() for line in block[1:] if line.strip())
    return [block[0] + (" " + rest if rest else "")]


def squeeze_blanks(lines: list[str]) -> list[str]:
    """Whitespace hygiene: never more than one consecutive blank line, no
    leading or trailing blanks. Blank lines are cosmetic in every output
    language; they carry no meaning."""
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out


class GeneratorBackend(ABC):
    name: str = "?"

    @abstractmethod
    def generate(self, index: ScaIndex, options: GenOptions) -> list[GeneratedFile]:
        ...
