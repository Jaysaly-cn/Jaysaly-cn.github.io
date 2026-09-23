"""Deterministic overlapping character windows; offsets refer to immutable source text."""
SIZE = 3600
OVERLAP = 240
VERSION = 'chars-v1'


def plan(text):
    result = []
    start = 0
    while start < len(text):
        end = min(start + SIZE, len(text))
        if end < len(text):
            # Prefer a paragraph/sentence boundary in the last 20% of the window.
            boundary = max(text.rfind(c, end - 720, end) for c in ('\n', '。', '！', '？'))
            if boundary >= 0:
                end = boundary + 1
        result.append({'index': len(result), 'start': start, 'end': end})
        if end == len(text):
            break
        start = end - OVERLAP
    return result


def covered(windows):
    end = total = 0
    for w in sorted(windows, key=lambda w: w['start']):
        total += max(0, w['end'] - max(end, w['start']))
        end = max(end, w['end'])
    return total
