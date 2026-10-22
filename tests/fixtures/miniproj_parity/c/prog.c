/* The parity program: a tiny pipeline that every indexed language spells the same way. */

/* clean normalizes the lines. */
static const char *clean(void)
{
    return "a\nb";
}

/* load produces the raw lines. */
static const char *load(void)
{
    return clean();
}

/* summarize counts the lines. */
static int summarize(void)
{
    const char *lines = clean();
    int n = 0;
    while (lines[n] != '\0') {
        n++;
    }
    return n;
}

static int compute_alpha(void)
{
    const char *lines = clean();
    return (lines[0] != '\0') + 1;
}

static int compute_beta(void)
{
    const char *lines = clean();
    return (lines[0] != '\0') + 2;
}

/* island: nobody calls this and nothing consumes its result. */
static int island(void)
{
    return 7;
}

int main(void)
{
    load();
    summarize();
    does_not_exist();
    return 0;
}
