"""Exact line diff; offsets are Unicode code points, end-exclusive, not bytes."""
from difflib import SequenceMatcher
from hashlib import sha256


def digest(text):
    return sha256(text.encode('utf-8')).hexdigest()


def validate_text(text):
    if not text or len(text)>20000:
        raise ValueError('正文需为1至20000个字符')
    lines=text.splitlines(keepends=True)
    if len(lines)>500 or any(len(line)>4000 for line in lines):
        raise ValueError('正文最多500行，每行最多4000个字符')
    return lines


def compare(old,new):
    left,right=validate_text(old),validate_text(new)
    def offsets(lines):
        result=[0]
        for line in lines:result.append(result[-1]+len(line))
        return result
    a,b=offsets(left),offsets(right)
    # Bounded to 500 lines per version; no character-level quadratic pass.
    operations=[]
    for tag,i,j,k,l in SequenceMatcher(None,left,right,autojunk=False).get_opcodes():
        operations.append({'kind':tag,'old_start':a[i],'old_end':a[j],
                           'new_start':b[k],'new_end':b[l],
                           'old_text':old[a[i]:a[j]],'new_text':new[b[k]:b[l]]})
    return {'algorithm':'difflib.SequenceMatcher lines, autojunk=False',
            'offset_unit':'Unicode code points, zero-based, end-exclusive',
            'old_sha256':digest(old),'new_sha256':digest(new),
            'operations':operations,'change_count':sum(op['kind']!='equal' for op in operations)}
