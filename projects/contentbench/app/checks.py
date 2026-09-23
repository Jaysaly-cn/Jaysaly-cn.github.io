import re
import unicodedata

CHANNELS = {'小红书': 600, '公众号': 1800, '短信': 70, '邮件': 1200}


def normalize(text):
    return unicodedata.normalize('NFKC', text).casefold()


def numbers(text):
    return set(re.findall(r'\d+(?:\.\d+)?%?', normalize(text)))


def check(brief, channel, title, body, fact_ids):
    text = normalize(title + '\n' + body)
    facts = {f['id']: f for f in brief['facts']}
    issues = []
    if len(body) > CHANNELS[channel]:
        issues.append({'code': 'length', 'detail': f'正文 {len(body)} 字符，超过 {CHANNELS[channel]} 字符工作台上限'})
    for word in brief['forbidden']:
        if normalize(word) in text:
            issues.append({'code': 'forbidden', 'detail': '包含禁用词：' + word})
    if brief['required_phrase'] and normalize(brief['required_phrase']) not in normalize(body):
        issues.append({'code': 'required', 'detail': '正文缺少必带说明：' + brief['required_phrase']})
    if not fact_ids:
        issues.append({'code': 'facts', 'detail': '请关联至少一条品牌事实'})
    # This is a lexical guard, not an entailment judge. Human review remains mandatory.
    known = numbers('\n'.join(facts[i]['text'] for i in fact_ids if i in facts))
    unknown = sorted(numbers(title + '\n' + body) - known)
    if unknown:
        issues.append({'code': 'numbers', 'detail': '关联事实未出现的数字：' + '、'.join(unknown)})
    return {'blockers': issues, 'body_characters': len(body), 'limit': CHANNELS[channel],
            'human_checks': ['逐句核对事实含义、条件与来源', '确认措辞、权益说明与目标渠道适用性'],
            'semantic_verified': False}
