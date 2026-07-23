"""Edge-case corpus distilled from slamface findings (#11 flask, #12 click)."""


def process(result: str) -> str:
    """Param named 'result' — must not collide with the wrapper's result binding."""
    return result.strip()


def clone() -> str:
    """Zero-arg function named 'clone' — must not hide Object.clone() in Java."""
    return "copy"


def toString(x: int) -> str:
    """Object-member name with args — hidden-instance-method hazard either way."""
    return str(x)
