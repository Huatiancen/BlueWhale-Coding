from store import next_task_id

tasks = [{"id": 10}, {"id": 2}]
snapshot = [dict(item) for item in tasks]
assert next_task_id(tasks) == 11
assert tasks == snapshot
assert next_task_id([]) == 1
