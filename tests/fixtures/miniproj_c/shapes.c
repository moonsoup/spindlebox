/* shapes measures rectangles and reports them through textkit. */
#include <stdio.h>
#include "textkit.h"

struct Rect {
    double w;
    double h;
};

/* area returns the area of a rectangle. */
double area(const struct Rect *r)
{
    return r->w * r->h;
}

/* describe writes a one-line description of a rectangle. */
int describe(const struct Rect *r, char *out, unsigned long cap)
{
    double a = area(r);
    return snprintf(out, cap, "rect %f", a);
}

/* main runs a tiny smoke test. */
int main(int argc, char **argv)
{
    struct Rect r;
    r.w = 2.0;
    r.h = 3.0;
    printf("%f\n", area(&r));
    return count_words(argv[0]);
}
