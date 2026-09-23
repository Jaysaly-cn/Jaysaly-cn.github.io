import re


def locate(transcript,quote,owner,attendees):
    positions=[m.start() for m in re.finditer(re.escape(quote),transcript)]
    if not positions:
        raise ValueError('引用不是会议记录的连续原文')
    if owner:
        if owner not in attendees:
            raise ValueError('负责人不在参会名单中')
        positions=[p for p in positions if owner in quote or re.search(
            r'(?:^|[\n。！？])\s*'+re.escape(owner)+r'[：:]\s*$',transcript[:p])]
        if not positions:
            raise ValueError('引用或紧邻发言人前缀中没有负责人；不明确时请留空')
    if len(positions)!=1:
        raise ValueError('原文出现多处相同片段，请扩大引用以消除歧义')
    return positions[0], 'inside_quote' if owner and owner in quote else 'speaker_prefix' if owner else 'unknown'
