"""Small-corpus lexical retrieval; not an embedding/semantic search claim."""
import re
from rank_bm25 import BM25Plus


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9_]+", text.lower())
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return words


def chunks(text: str, size: int = 650) -> list[str]:
    text = text.strip()
    return [text[i:i + size] for i in range(0, len(text), size - 100)]


def search(documents: list[dict], query: str, limit: int = 4) -> list[dict]:
    passages = []
    for doc in documents:
        for index, content in enumerate(chunks(doc['content'])):
            passages.append({'document_id': doc['id'], 'title': doc['title'],
                             'version': doc['version'], 'chunk': index,
                             'content': content, 'source': doc['source']})
    if not passages:
        return []
    corpus = [tokens(p['title'] + ' ' + p['content']) for p in passages]
    query_tokens = tokens(query)
    if not query_tokens or not any(corpus):
        return []
    # ponytail: rebuild for small corpora; cache by corpus revision if profiling warrants it.
    scores = BM25Plus(corpus, delta=0).get_scores(query_tokens)
    results = []
    for i in sorted(range(len(scores)), key=lambda x: scores[x], reverse=True):
        if scores[i] <= 0:
            continue
        overlap = set(query_tokens) & set(corpus[i])
        results.append({**passages[i], 'score': round(float(scores[i]), 4),
                        'matched_terms': sorted(overlap)})
        if len(results) >= limit:
            break
    return results
