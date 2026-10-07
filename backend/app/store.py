import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meetings (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, file_name TEXT NOT NULL,
              hash TEXT UNIQUE NOT NULL, original BLOB NOT NULL, date TEXT, source_url TEXT,
              duration REAL, cue_count INTEGER, status TEXT DEFAULT 'pending', error TEXT,
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS cues (
              meeting_id TEXT REFERENCES meetings(id) ON DELETE CASCADE, idx INTEGER,
              start REAL, end REAL, speaker TEXT, text TEXT, source_id TEXT,
              PRIMARY KEY(meeting_id, idx));
            CREATE TABLE IF NOT EXISTS chunks (
              id INTEGER PRIMARY KEY, meeting_id TEXT REFERENCES meetings(id) ON DELETE CASCADE,
              cue_start INTEGER, cue_end INTEGER, start REAL, end REAL, text TEXT,
              embedding TEXT, embedding_model TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(text, tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT, meeting_id TEXT REFERENCES meetings(id), created_at TEXT);
            CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, chat_id TEXT REFERENCES chats(id), role TEXT, content TEXT, citations TEXT, usage TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS usage (id INTEGER PRIMARY KEY, operation TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost REAL, estimated INTEGER, created_at TEXT);
            CREATE TABLE IF NOT EXISTS deleted_imports (hash TEXT PRIMARY KEY);
            ''')
            if 'owner' not in {r['name'] for r in db.execute('PRAGMA table_info(usage)')}:
                db.execute('ALTER TABLE usage ADD COLUMN owner TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_meeting(self, title, file_name, original, cues, chunks, date, source_url, automatic=False):
        digest = hashlib.sha256(original).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id FROM meetings WHERE hash=?', (digest,)).fetchone()
            if old:
                return self.summary(old['id'], db), False
            if automatic and db.execute('SELECT 1 FROM deleted_imports WHERE hash=?', (digest,)).fetchone():
                return None, False
            db.execute('DELETE FROM deleted_imports WHERE hash=?', (digest,))
            mid = str(uuid.uuid4())
            db.execute('INSERT INTO meetings(id,title,file_name,hash,original,date,source_url,duration,cue_count,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (mid, title, file_name, digest, original, date, source_url, max(c.end for c in cues), len(cues), now()))
            db.executemany('INSERT INTO cues VALUES(?,?,?,?,?,?,?)', [(mid, c.index, c.start, c.end, c.speaker, c.text, c.source_id) for c in cues])
            for c in chunks:
                cursor = db.execute('INSERT INTO chunks(meeting_id,cue_start,cue_end,start,end,text) VALUES(?,?,?,?,?,?)', (mid, c.cue_start, c.cue_end, c.start, c.end, c.text))
                db.execute('INSERT INTO search_index(rowid,text) VALUES(?,?)', (cursor.lastrowid, c.text))
            return self.summary(mid, db), True

    def summary(self, mid, db):
        row = db.execute('SELECT id,title,file_name,date,source_url,duration,cue_count,status,error,created_at FROM meetings WHERE id=?', (mid,)).fetchone()
        if not row:
            raise KeyError('Reunión no encontrada.')
        return dict(row)

    def list_meetings(self):
        with self.connect() as db:
            ids = db.execute('SELECT id FROM meetings ORDER BY created_at DESC').fetchall()
            return [self.summary(r['id'], db) for r in ids]

    def meeting(self, mid):
        with self.connect() as db:
            result = self.summary(mid, db)
            result['cues'] = [dict(r) for r in db.execute('SELECT idx,start,end,speaker,text FROM cues WHERE meeting_id=? ORDER BY idx', (mid,))]
            return result

    def original(self, mid):
        with self.connect() as db:
            row = db.execute('SELECT original FROM meetings WHERE id=?', (mid,)).fetchone()
            if not row:
                raise KeyError('Reunión no encontrada.')
            return row[0]

    @staticmethod
    def available_citations(citations, available):
        # Historical answer text remains, but deleted source excerpts must go.
        return [dict({k:v for k,v in s.items() if k not in ('text', 'chunk_id')}, deleted=True)
                if s['meeting_id'] not in available else s for s in citations]

    def delete_meeting(self, mid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT hash FROM meetings WHERE id=?', (mid,)).fetchone()
            if not row:
                raise KeyError('Reunión no encontrada.')
            db.execute('INSERT OR IGNORE INTO deleted_imports(hash) VALUES(?)', (row['hash'],))
            chat_ids = [r[0] for r in db.execute('SELECT id FROM chats WHERE meeting_id=?', (mid,))]
            db.execute('DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE meeting_id=?)', (mid,))
            db.execute('DELETE FROM chats WHERE meeting_id=?', (mid,))
            db.execute('DELETE FROM search_index WHERE rowid IN (SELECT id FROM chunks WHERE meeting_id=?)', (mid,))
            db.execute('DELETE FROM meetings WHERE id=?', (mid,))
            available = {r[0] for r in db.execute('SELECT id FROM meetings')}
            for message in db.execute("SELECT id,citations FROM messages WHERE citations IS NOT NULL AND citations != '[]'").fetchall():
                sources = json.loads(message['citations'])
                if any(s['meeting_id'] == mid for s in sources):
                    db.execute('UPDATE messages SET citations=? WHERE id=?',
                               (json.dumps(self.available_citations(sources, available)), message['id']))
            return dict(deleted=True, deleted_chat_ids=chat_ids)

    def chunks(self, mid=None):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT c.*,m.title,m.date FROM chunks c JOIN meetings m ON m.id=c.meeting_id' + (' WHERE meeting_id=?' if mid else '') + ' ORDER BY c.id', (mid,) if mid else ())]

    def save_embeddings(self, ids, vectors, model, meeting_id=None):
        with self.connect() as db:
            # A concurrent delete/re-upload can reuse SQLite integer IDs.
            sql = 'UPDATE chunks SET embedding=?,embedding_model=? WHERE id=?'
            if meeting_id:
                sql += ' AND meeting_id=?'
            db.executemany(sql, [(json.dumps(v), model, cid, meeting_id) if meeting_id else (json.dumps(v), model, cid)
                                 for cid, v in zip(ids, vectors, strict=True)])

    def status(self, mid, status, error=None):
        with self.connect() as db:
            db.execute('UPDATE meetings SET status=?,error=? WHERE id=?', (status, error, mid))

    def lexical(self, expression, mid, limit):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT c.id FROM search_index f JOIN chunks c ON c.id=f.rowid WHERE search_index MATCH ?' + (' AND c.meeting_id=?' if mid else '') + ' ORDER BY bm25(search_index) LIMIT ?', (expression, mid, limit) if mid else (expression, limit))]

    def create_chat(self, mid=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if mid:
                self.summary(mid, db)
            item = dict(id=str(uuid.uuid4()), title='Nuevo chat', meeting_id=mid, created_at=now())
            db.execute('INSERT INTO chats VALUES(:id,:title,:meeting_id,:created_at)', item)
            return item

    def chats(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM chats ORDER BY created_at DESC')]

    def delete_chat(self, cid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM chats WHERE id=?', (cid,)).fetchone():
                raise KeyError('Chat no encontrado.')
            db.execute('DELETE FROM messages WHERE chat_id=?', (cid,))
            db.execute('DELETE FROM chats WHERE id=?', (cid,))
            return {'deleted':True}

    def chat(self, cid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM chats WHERE id=?', (cid,)).fetchone()
            if not row:
                raise KeyError('Chat no encontrado.')
            result = dict(row)
            result['messages'] = [dict(r) for r in db.execute('SELECT * FROM messages WHERE chat_id=? ORDER BY rowid', (cid,))]
            for m in result['messages']:
                m['citations'] = json.loads(m['citations'] or '[]')
                m['usage'] = json.loads(m['usage'] or '{}')
            return result

    def save_turn(self, cid, question, answer, citations, usage):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM chats WHERE id=?', (cid,)).fetchone():
                raise KeyError('Chat no encontrado.')
            available = {r[0] for r in db.execute('SELECT id FROM meetings')}
            citations = self.available_citations(citations, available)
            for role, content, sources, cost in [('user', question, [], {}), ('assistant', answer, citations, usage)]:
                db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?)', (str(uuid.uuid4()), cid, role, content, json.dumps(sources), json.dumps(cost), now()))
            db.execute("UPDATE chats SET title=? WHERE id=? AND title='Nuevo chat'", (question[:65], cid))
            return citations

    def record_usage(self, operation, model, usage, owner=None):
        with self.connect() as db:
            db.execute('INSERT INTO usage(operation,model,input_tokens,output_tokens,cost,estimated,created_at,owner) VALUES(?,?,?,?,?,?,?,?)', (operation, model, usage.get('input_tokens', 0), usage.get('output_tokens', 0), usage['cost'], usage.get('estimated', True), now(), owner))

    def costs(self, owner=None):
        with self.connect() as db:
            sql = "SELECT COALESCE(SUM(cost),0) AS total, COALESCE(SUM(CASE WHEN substr(created_at,1,10)=date('now') THEN cost ELSE 0 END),0) AS today, COUNT(*) AS calls FROM usage"
            return dict(db.execute(sql + (' WHERE owner=?' if owner else ''), (owner,) if owner else ()).fetchone())
