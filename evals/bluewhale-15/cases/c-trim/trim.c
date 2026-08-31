#include <ctype.h>
#include <string.h>

void trim_in_place(char *value) {
    char *start = value;
    while (*start && isspace((unsigned char)*start)) start++;
    if (start != value) memmove(value, start, strlen(start) + 1);
}
