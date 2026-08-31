def completion_rate(tasks: list[dict[str, object]]) -> float:
    if not tasks:
        return 0.0
    completed = sum(bool(task.get("done")) for task in tasks)
    return round(completed // len(tasks), 1)
