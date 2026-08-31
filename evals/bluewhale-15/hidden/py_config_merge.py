from config import merge_config

defaults = {"port": 80, "host": "localhost"}
user = {"port": 9000}
assert merge_config(defaults, user) == {"port": 9000, "host": "localhost"}
assert defaults == {"port": 80, "host": "localhost"}
assert user == {"port": 9000}
