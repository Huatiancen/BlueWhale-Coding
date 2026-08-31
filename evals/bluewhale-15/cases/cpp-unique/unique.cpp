#include <vector>

std::vector<int> unique_preserving_order(const std::vector<int>& values) {
    std::vector<int> result;
    for (int value : values) {
        if (result.empty() || result.back() != value) result.push_back(value);
    }
    return result;
}
