"""Fixture with deliberately planted gaps and a clean workflow chain."""


def load(path: str) -> list[str]:
    """Stage 1: read raw lines. Provides 'load_result'."""
    with open(path) as f:
        return f.read().splitlines()


def clean(load_result: list[str]) -> list[str]:
    """Stage 2: consumes load's output by ctx key. Provides 'clean_result'."""
    return [line.strip() for line in load_result if line.strip()]


def summarize(clean_result: list[str]) -> int:
    """Stage 3: consumes clean's output. Provides 'summarize_result'."""
    return len(clean_result)


def orphan(unprovided_key: str) -> str:
    """A required ctx key ('unprovided_key') that nothing in the index provides."""
    return unprovided_key.upper()


def caller() -> int:
    """Calls a name that does not exist as any item and isn't an import → unresolvable."""
    return does_not_exist_anywhere()  # noqa: F821


def compute_alpha(load_result: list[str]) -> int:
    """Near-duplicate of compute_beta: same sig class, same ctx shape."""
    return len(load_result)


def compute_beta(load_result: list[str]) -> int:
    """Near-duplicate of compute_alpha: same sig class, same ctx shape."""
    return len(load_result) + 1


def used_helper(x: int) -> int:
    return x * 2


def main() -> int:
    """Entrypoint: calls used_helper, so used_helper is not dead."""
    return used_helper(3)
