def parse_row(line: str) -> list[str]:
    return [part.strip().strip('"') for part in line.split(",")]
