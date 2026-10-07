import json
import math
import re


def retrieve(store, vector, query, meeting_id=None, embedding_model=None, limit=10):
    rows = store.chunks(meeting_id)
    words = re.findall(r'[^\W_]+', query, re.UNICODE)[:40]
    expression = ' OR '.join('"' + w + '"' for w in words)
    lexical = store.lexical(expression, meeting_id, limit * 4) if expression else []
    scores = {cid: 1 / (60 + rank) for rank, cid in enumerate(lexical, 1)}
    if vector:
        norm = math.sqrt(sum(v*v for v in vector)) or 1
        semantic = []
        for row in rows:
            if not row['embedding'] or row['embedding_model'] != embedding_model:
                continue
            candidate = json.loads(row['embedding'])
            if len(candidate) != len(vector):
                continue
            denom = norm * (math.sqrt(sum(v*v for v in candidate)) or 1)
            similarity = sum(a*b for a,b in zip(vector, candidate)) / denom
            if similarity >= .35:
                semantic.append((similarity, row['id']))
        for rank, (_, cid) in enumerate(sorted(semantic, reverse=True)[:limit*4], 1):
            scores[cid] = scores.get(cid, 0) + 1 / (60 + rank)
    selected = sorted((r for r in rows if r['id'] in scores), key=lambda r: scores[r['id']], reverse=True)[:limit]
    return [{k:v for k,v in row.items() if k not in ('embedding', 'embedding_model')} for row in selected]
