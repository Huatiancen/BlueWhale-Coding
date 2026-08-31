from slug import slugify

assert slugify("  Blue___Whale!!! Agent  ") == "blue-whale-agent"
assert slugify("Already-clean") == "already-clean"
