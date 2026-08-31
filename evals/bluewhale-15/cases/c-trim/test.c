#include <assert.h>
#include <string.h>

void trim_in_place(char *value);

int main(void) {
    char value[] = "  blue whale  ";
    trim_in_place(value);
    assert(strcmp(value, "blue whale") == 0);
    return 0;
}
