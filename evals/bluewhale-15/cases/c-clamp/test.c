#include <assert.h>

int clamp_int(int value, int minimum, int maximum);

int main(void) {
    assert(clamp_int(-2, 0, 10) == 0);
    assert(clamp_int(12, 0, 10) == 10);
    return 0;
}
