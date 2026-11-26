"""Update RESULTS.md in place: append a history row, replace one set's detail section."""


def _split(text: str, name: str) -> tuple[str, str, str]:
    start, end = f"<!-- {name}:start -->\n", f"<!-- {name}:end -->"
    before, rest = text.split(start, 1)
    inside, after = rest.split(end, 1)
    return before + start, inside, end + after


def update(text: str, row: str, section: str, body: str) -> str:
    before, rows, after = _split(text, "runs")
    text = before + rows + row + "\n" + after
    before, _, after = _split(text, section)
    return before + body.strip("\n") + "\n" + after
