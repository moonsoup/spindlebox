/* app is a synthetic C program for issue #38: libc calls and C entry points. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void)
{
    char *p = malloc(8);
    printf("%d\n", (int)strlen(p));
    free(p);
    frobnicate_typo(p);
    return 0;
}

/* A Python entry-point spelling: in C an uncalled setup is dead. */
void setup(void)
{
}
