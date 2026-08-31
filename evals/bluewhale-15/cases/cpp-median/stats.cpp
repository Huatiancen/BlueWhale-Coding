#include <stdexcept>
#include <vector>

double median(const std::vector<double>& values) {
    if (values.empty()) throw std::invalid_argument("empty values");
    return values[values.size() / 2];
}
