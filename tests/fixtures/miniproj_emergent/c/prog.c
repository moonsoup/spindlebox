/* The emergent program: a 6-deep chain, mutual recursion, and an unreachable island. */

static int step6(void)
{
    return 1;
}

static int step5(void)
{
    return step6() + 1;
}

static int step4(void)
{
    return step5() + 1;
}

static int step3(void)
{
    return step4() + 1;
}

static int step2(void)
{
    return step3() + 1;
}

static int step1(void)
{
    return step2() + 1;
}

static int pong(void);

static int ping(void)
{
    return pong() + 1;
}

static int pong(void)
{
    return ping() + 1;
}

static int lonely_b(void);

static int lonely_a(void)
{
    return lonely_b() + 1;
}

static int lonely_b(void)
{
    return lonely_a() + 1;
}

int main(void)
{
    step1();
    ping();
    return 0;
}
