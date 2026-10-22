"""Functions used as values: decorators, higher-order shape, indirect calls (#39)."""


def deco(fn):
    return fn


def inc(x):
    return x + 1


HANDLERS = {"inc": inc}


@deco
def tagged():
    return 1


def apply(f, x):
    return f(x)


def make_adder(n):
    def adder(x):
        return x + n
    return adder


def dispatch(k, x):
    return HANDLERS[k](x)


def local_dispatch(k, x):
    table = {"inc": inc}
    return table[k](x)


class Router:
    routes = {"inc": inc}

    @staticmethod
    def static_route(x):
        return x

    def route(self, k, x):
        return self.routes[k](x)
