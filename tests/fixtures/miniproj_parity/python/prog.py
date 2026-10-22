"""The parity program: a tiny pipeline that every indexed language spells the same way."""


def load() -> list[str]:
    """Produce the raw lines."""
    return clean()


def clean() -> list[str]:
    """Normalize the lines."""
    return ["a", "b"]


def summarize() -> int:
    """Count the lines (through a language builtin)."""
    return len(clean())


def compute_alpha() -> int:
    return len(clean()) + 1


def compute_beta() -> int:
    return len(clean()) + 2


def island() -> int:
    """Nobody calls this and nothing consumes its result."""
    return 7


def main() -> None:
    load()
    summarize()
    does_not_exist()
