#include <cassert>
#include <vector>

std::vector<int> unique_preserving_order(const std::vector<int>& values);

int main() {
    assert((unique_preserving_order({1, 2, 1, 3}) == std::vector<int>{1, 2, 3}));
}
