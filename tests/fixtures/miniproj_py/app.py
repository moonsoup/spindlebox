import os

from util.io import read_lines


def home() -> str:
    """Locate the findexer home directory."""
    return os.environ["FINDEXER_HOME"]


def make_counter():
    count = 0

    def bump() -> int:
        nonlocal count
        count += 1
        return count

    return bump


def make_reader(prefix: str):
    def read(name: str) -> list[str]:
        return read_lines(prefix + name)

    return read


def double(x: int) -> int:
    return x * 2


def triple(x: int) -> int:
    return x * 3
