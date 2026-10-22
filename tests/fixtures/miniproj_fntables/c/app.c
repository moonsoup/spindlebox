static int alpha_handler(int x) { return x + 1; }
static int on_beta(int x) { return x * 2; }

struct handlers { int (*alpha)(int); int (*beta)(int); };

static struct handlers HANDLERS = { .alpha = alpha_handler, .beta = on_beta };

static int first_step(int x) { return x; }
static int second_step(int x) { return x; }

static int (*PIPE[])(int) = { first_step, second_step };

int dispatch(int i, int x) { return PIPE[i](x); }
