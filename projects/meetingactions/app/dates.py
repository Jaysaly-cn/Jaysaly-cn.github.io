import re
from datetime import date, timedelta


def resolve(phrase, meeting_date):
    """Only explicit supported phrases; ambiguous deadlines stay empty for review."""
    base = date.fromisoformat(meeting_date)
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', phrase):
            return date.fromisoformat(phrase).isoformat()
    except ValueError:
        return ''
    if phrase in ('今天', '明天', '后天'):
        try:
            return (base + timedelta(days={'今天':0,'明天':1,'后天':2}[phrase])).isoformat()
        except OverflowError:
            return ''
    match = re.fullmatch(r'(本|下)周([一二三四五六日天])', phrase)
    if match:
        index = '一二三四五六日'.index(match[2].replace('天', '日'))
        offset = index-base.weekday()+(7 if match[1]=='下' else 0)
        try:
            return (base+timedelta(days=offset)).isoformat()
        except OverflowError:
            return ''
    return ''
