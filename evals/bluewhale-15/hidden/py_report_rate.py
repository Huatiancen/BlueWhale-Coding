from report import completion_rate

assert completion_rate([]) == 0.0
assert completion_rate([{"done": True}, {"done": True}, {"done": False}]) == 0.7
