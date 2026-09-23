import csv
import io
from datetime import date, datetime, timezone


def safe_csv(value):
    text = str(value)
    return "'"+text if text.lstrip().startswith(('=','+','-','@','\t','\r')) else text


def csv_content(rows):
    out = io.StringIO(newline='')
    writer = csv.writer(out)
    keys = ['title','owner','due_date','state','meeting_title','quote','review_note','completion_note']
    writer.writerow(keys)
    for row in rows:
        writer.writerow([safe_csv(row[k]) for k in keys])
    return '\ufeff'+out.getvalue()


def escape(text):
    return text.replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n',r'\n').replace(';',r'\;').replace(',',r'\,')


def fold(line):
    # RFC 5545 octet folding: never split a UTF-8 codepoint.
    parts, current = [], ''
    for char in line:
        if len((current+char).encode('utf-8')) > 75:
            parts.append(current)
            current = ' '
        current += char
    return '\r\n'.join(parts+[current])


def calendar(rows):
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//MeetingActions//Task Deadlines//ZH','CALSCALE:GREGORIAN']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    for r in rows:
        if r['state'] in ('done','cancelled') or not r['due_date']:
            continue
        due = date.fromisoformat(r['due_date'])
        lines += ['BEGIN:VEVENT',f'UID:{r["id"]}@meetingactions.local',f'DTSTAMP:{stamp}',
                  f'SEQUENCE:{r["version"]}',f'DTSTART;VALUE=DATE:{due:%Y%m%d}',
                  'DURATION:P1D',
                  'SUMMARY:'+escape(r['title']),
                  'DESCRIPTION:'+escape(f'负责人：{r["owner"]}\n会议：{r["meeting_title"]}\n原文：{r["quote"]}'),
                  'END:VEVENT']
    return '\r\n'.join(fold(line) for line in lines+['END:VCALENDAR'])+'\r\n'
