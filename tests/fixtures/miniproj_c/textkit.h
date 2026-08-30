/* Public interface of the tiny text kit. */
#ifndef TEXTKIT_H
#define TEXTKIT_H

#include <stddef.h>

#define TEXTKIT_MAX_LINES 64

typedef struct Buffer {
    char *data;
    unsigned long len;
} Buffer;

enum Mode {
    MODE_READ,
    MODE_WRITE
};

char *read_lines(const char *path);
char **split_words(const char *text, int *out_count);
int count_words(const char *text);
double average_len(const struct Buffer *buf);
void apply_bytes(struct Buffer *buf, int (*fn)(int));
int sum_all(int n, ...);
const char *home(void);
void reset(void);
int width_of(int);

#endif
