"""The emergent program: a 6-deep chain, mutual recursion, and an unreachable island."""


def step1() -> int:
    return step2() + 1


def step2() -> int:
    return step3() + 1


def step3() -> int:
    return step4() + 1


def step4() -> int:
    return step5() + 1


def step5() -> int:
    return step6() + 1


def step6() -> int:
    return 1


def ping() -> int:
    return pong() + 1


def pong() -> int:
    return ping() + 1


def lonely_a() -> int:
    return lonely_b() + 1


def lonely_b() -> int:
    return lonely_a() + 1


def main() -> None:
    step1()
    ping()
