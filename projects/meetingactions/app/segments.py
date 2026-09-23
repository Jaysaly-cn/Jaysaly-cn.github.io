"""Contiguous immutable transcript ranges; offsets are Python Unicode characters."""
LIMIT = 4000
VERSION = 'contiguous-v1'


def split(text):
    result, start = [], 0
    while start < len(text):
        end = min(start + LIMIT, len(text))
        hard = False
        if end < len(text):
            # Prefer a recent paragraph/sentence end without dropping any text.
            lower = start + LIMIT // 2
            boundary = max(text.rfind(mark, lower, end) for mark in ('\n', '。', '！', '？', ';', '；'))
            if boundary >= lower:
                end = boundary + 1
            else:
                hard = True
        result.append({'index': len(result), 'start': start, 'end': end,
                       'chars': end - start, 'hard_split': hard})
        start = end
    return result


def matching_run(runs, segment, transcript_hash):
    for run in runs:
        read = run['trace'][0] if run['trace'] else {}
        if (read.get('segmentation') == VERSION and read.get('start') == segment['start']
                and read.get('end') == segment['end'] and read.get('sha256') == transcript_hash):
            return run
    return None
