#include <cassert>
#include <vector>

double median(const std::vector<double>& values);

int main() {
    assert(median(std::vector<double>{1, 3, 7}) == 3.0);
    assert(median(std::vector<double>{1, 3, 7, 9}) == 5.0);
}
