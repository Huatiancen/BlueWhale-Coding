def merge_config(defaults: dict[str, object], user: dict[str, object]) -> dict[str, object]:
    result = user.copy()
    result.update(defaults)
    return result
