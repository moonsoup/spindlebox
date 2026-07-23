def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


def greet(name: str, punct: str = "!") -> str:
    """Greet someone."""
    return f"hello {name}{punct}"


def wrap(ctx: str) -> str:
    """Wrap a string in brackets (param deliberately named ctx: regression for issue #1)."""
    return "[" + ctx + "]"


def reserved(final: int, override: int, macro: int) -> int:
    """Params named after Rust reserved keywords (pydantic T3): must r#-escape."""
    return final + override + macro

