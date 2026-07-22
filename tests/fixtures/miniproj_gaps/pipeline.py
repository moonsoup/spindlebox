"""Fixture with deliberately planted gaps and a clean workflow chain.

Planted:
- a clean 3-stage ctx workflow: load -> clean -> summarize
- near-duplicate pair: compute_alpha / compute_beta (same sig class + ctx shape)
- an unprovided *_result ctx key: orphan requires phantom_result
- an unresolvable call: dangler calls a name that is no item and no import
- a genuinely dead item: island (no caller, not an entrypoint, no ctx edges)
- non-gaps that must NOT be flagged: main (entrypoint) -> used_helper (called)
"""


def load(path: str) -> list[str]:
    """Stage 1: read raw lines. Provides 'load_result'."""
    with open(path) as f:
        data = f.read()
    return data.split("\n")


def clean(load_result: list[str]) -> list[str]:
    """Stage 2: consumes load's output by ctx key. Provides 'clean_result'."""
    return [line.strip() for line in load_result if line.strip()]


def summarize(clean_result: list[str]) -> int:
    """Stage 3: consumes clean's output. Provides 'summarize_result'."""
    return len(clean_result)


def compute_alpha(load_result: list[str]) -> int:
    """Near-duplicate of compute_beta: same sig class, same ctx requires."""
    return len(load_result)


def compute_beta(load_result: list[str]) -> int:
    """Near-duplicate of compute_alpha: same sig class, same ctx requires."""
    return len(load_result) + 1


def orphan(phantom_result: str) -> str:
    """Requires 'phantom_result' — a *_result key nothing in the index provides."""
    return phantom_result.upper()


def dangler() -> int:
    """Calls a bare name that is neither an item nor an import → unresolvable."""
    return does_not_exist_anywhere()  # noqa: F821


def island(x: int) -> int:
    """Genuinely dead: no caller, not an entrypoint, no ctx provider/consumer edge."""
    return x * 99


def used_helper(x: int) -> int:
    return x * 2


def main() -> int:
    """Entrypoint: calls used_helper, so used_helper is not dead."""
    return used_helper(3)
