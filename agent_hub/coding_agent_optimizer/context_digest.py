from __future__ import annotations


def digest_context(text: str, *, max_chars: int = 4000, preserve_markers: tuple[str, ...] = ("TODO", "FIXME", "error", "traceback")) -> str:
    text = str(text or "")
    if len(text) <= max_chars:
        return text
    marker = "\n\n[...context compacted...]\n\n"
    budget = max(0, max_chars - len(marker))
    important = _important_lines(text, preserve_markers=preserve_markers, max_chars=budget // 4)
    remaining = max(0, budget - len(important))
    head = text[: remaining // 2]
    tail = text[-(remaining - len(head)) :]
    if important:
        return f"{head}\n\n[...important lines...]\n{important}{marker}{tail}"
    return f"{head}{marker}{tail}"


def _important_lines(text: str, *, preserve_markers: tuple[str, ...], max_chars: int) -> str:
    lowered_markers = tuple(marker.lower() for marker in preserve_markers)
    rows = []
    for line in text.splitlines():
        lowered = line.lower()
        if any(marker in lowered for marker in lowered_markers):
            rows.append(line[:240])
        if sum(len(row) + 1 for row in rows) >= max_chars:
            break
    return "\n".join(rows)[:max_chars]
