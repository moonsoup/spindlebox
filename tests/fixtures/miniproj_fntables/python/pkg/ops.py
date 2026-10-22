"""Functions held in data: a dict, a list, two registries, a stray table."""


def alpha_handler(x):
    return x + 1


def on_beta(x):
    return x * 2


HANDLERS = {
    "alpha": alpha_handler,
    "beta": on_beta,
}


def dispatch(kind, x):
    return HANDLERS[kind](x)


def first_step(x):
    return x


def second_step(x):
    return x


PIPE = [first_step, second_step]


def run_pipe(x):
    for i in range(len(PIPE)):
        x = PIPE[i](x)
    return x


OPS = {}


def op(name):
    def wrap(fn):
        OPS[name] = {"fn": fn, "name": name}
        return fn
    return wrap


@op("upper")
def upper_op(ctx):
    return ctx


@op("lower")
def lower_op(ctx):
    return ctx


def run_op(name, ctx):
    return OPS[name]["fn"](ctx)


HOOKS = []


def add_hook(fn):
    HOOKS.append(fn)
    return fn


def hook_one(event):
    return event


add_hook(hook_one)


def fire(event):
    return HOOKS[0](event)


def unary(x):
    return x


def binary(x, y):
    return x + y


MIXED = {"one": unary, "two": binary}


def use_mixed(k):
    return MIXED[k](1)


def orphan(x):
    return x


ORPHANS = {"orphan": orphan}
