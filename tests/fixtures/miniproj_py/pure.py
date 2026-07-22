def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def greet(name: str, punct: str = "!") -> str:
    """Greet someone."""
    return f"hello {name}{punct}"


def wrap(ctx: str) -> str:
    """Wrap a string in brackets (param deliberately named ctx: regression for issue #1)."""
    return "[" + ctx + "]"
