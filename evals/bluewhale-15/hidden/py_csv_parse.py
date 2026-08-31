from csv_tools import parse_row

assert parse_row('"Blue ""Whale""",42,"a,b"') == ['Blue "Whale"', "42", "a,b"]
