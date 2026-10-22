/* Functions used as values: attributes, function pointers, dispatch tables (#39). */

static int inc(int x) {
    return x + 1;
}

static int (*HANDLERS[])(int) = {inc};

__attribute__((unused)) static int tagged(void) {
    return 1;
}

int apply(int (*f)(int), int x) {
    return f(x);
}

int (*make_adder(int n))(int) {
    return n ? inc : inc;
}

int dispatch(int k, int x) {
    return HANDLERS[k](x);
}
