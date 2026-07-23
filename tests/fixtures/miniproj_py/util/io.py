import json
import os

try:
    import requests  # noqa: F401  (external dep on purpose — dep extraction sees it)
except ImportError:  # dispatch imports this module; it must load in minimal envs
    requests = None


def read_lines(path: str) -> list[str]:
    """Read lines from a file."""
    with open(path) as f:
        return f.read().splitlines()


def exists(path: str) -> bool:
    """Check whether a path exists."""
    return os.path.exists(path)


def parse_blob(blob):
    return json.loads(blob)


class Reader:
    def __init__(self, path: str):
        self.path = path
        self.count = 0

    def read(self) -> list[str]:
        self.count += 1
        return read_lines(self.path)

    def peek(self) -> str:
        return self.path
