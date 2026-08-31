int clamp_int(int value, int minimum, int maximum) {
    if (value < minimum) return maximum;
    if (value > maximum) return minimum;
    return value;
}
