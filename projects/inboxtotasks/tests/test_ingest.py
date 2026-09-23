from email.message import EmailMessage
from hashlib import sha256
import pytest
from app.ingest import parse, MAX_BYTES
from app import store


def mail(body='请小林在周五前提交方案。', mid='<synthetic@example.invalid>'):
    msg=EmailMessage()
    msg['Subject']='项目方案 · 合成示例'
    msg['From']='演示同事 <sender@example.invalid>'
    msg['To']='recipient@example.invalid'
    if mid:msg['Message-ID']=mid
    msg.set_content(body)
    return msg


def test_plain_unicode_and_hashes():
    raw=mail().as_bytes();result=parse(raw)
    assert result['subject']=='项目方案 · 合成示例'
    assert result['body']=='请小林在周五前提交方案。'
    assert result['sha256']==sha256(raw).hexdigest()
    assert result['body_sha256']==sha256(result['body'].encode()).hexdigest()


def test_plain_preferred_and_attachment_not_task_body():
    msg=mail();msg.add_alternative('<p>其他HTML内容</p>',subtype='html')
    msg.add_attachment('附件里的任务不得提取',filename='tasks.txt')
    result=parse(msg.as_bytes())
    assert result['body']=='请小林在周五前提交方案。'
    assert any('附件' in w for w in result['warnings'])


def test_html_as_text_no_remote_requests_or_script():
    msg=mail();msg.set_content('<head><style>bad</style></head><p>请提交方案</p><script>alert(1)</script><img src="https://example.invalid/tracker"><p>周五前</p>',subtype='html')
    result=parse(msg.as_bytes())
    assert '请提交方案' in result['body'] and '周五前' in result['body']
    assert 'alert' not in result['body'] and 'tracker' not in result['body'] and 'bad' not in result['body']
    assert result['body_type']=='text/html'


@pytest.mark.parametrize('raw', [b'', b'x'*(MAX_BYTES+1), b'not an email', b'Subject: a\nSubject: b\n\nbody', b'Subject: a\nContent-Type: text/plain; charset=bad-encoding\n\nbody'], ids=['empty','oversize','no-headers','duplicate-header','unknown-charset'])
def test_invalid_input_rejected(raw):
    with pytest.raises(ValueError):parse(raw)


def test_attachment_only_rejected():
    msg=EmailMessage();msg['Subject']='只有附件';msg.add_attachment(b'content',maintype='application',subtype='octet-stream',filename='a.bin')
    with pytest.raises(ValueError):parse(msg.as_bytes())


def test_duplicate_and_conflicting_message_id_preserve_both(tmp_path):
    path=tmp_path/'inbox.db';store.initialize(path)
    raw=mail().as_bytes();first=store.import_message(path,raw)
    again=store.import_message(path,raw)
    assert again['duplicate'] and first['id']==again['id']
    changed=store.import_message(path,mail('日期改成下周一。').as_bytes())
    assert changed['message_id_conflicts']==[first['id']] and not changed['duplicate']
    assert store.message(path,first['id'])['message_id_conflicts']==[changed['id']]
    with store.connect(path) as db:
        assert db.execute('SELECT raw FROM messages WHERE id=?',(first['id'],)).fetchone()['raw']==raw
    store.initialize(path)
    assert len(store.messages(path))==2


def test_no_message_id_does_not_merge_different_messages(tmp_path):
    path=tmp_path/'inbox.db';store.initialize(path)
    a=store.import_message(path,mail(mid=None).as_bytes())
    b=store.import_message(path,mail('另一个任务。',mid=None).as_bytes())
    assert a['id']!=b['id'] and not b['message_id_conflicts']


def test_failed_import_is_atomic(tmp_path):
    path=tmp_path/'inbox.db';store.initialize(path)
    with pytest.raises(ValueError):store.import_message(path,b'bad input')
    assert store.messages(path)==[]
