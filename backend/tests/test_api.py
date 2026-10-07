from fastapi.testclient import TestClient
import pytest
import hashlib
from app.main import create_app
from test_core import SAMPLE
from test_service import FakeProvider


def test_upload_duplicate_reader_and_errors(tmp_path):
    app = create_app(tmp_path / 'data.sqlite', imports_dir=tmp_path / 'imports', provider=FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        assert client.get('/api/health').status_code == 200
        first = client.post('/api/meetings', files={'file':('test.vtt', SAMPLE)}, data={'title':'Mi reunión','date':'2026-10-01'})
        assert first.status_code == 200
        mid = first.json()['meeting']['id']
        duplicate = client.post('/api/meetings', files={'file':('other.vtt', SAMPLE)})
        assert duplicate.json()['created'] is False
        assert len(client.get('/api/meetings').json()) == 1
        assert client.get('/api/meetings/' + mid).json()['date'] == '2026-10-01'
        assert client.get('/api/meetings/' + mid + '/original').content == SAMPLE
        assert client.post('/api/meetings', files={'file':('test.vtt', b'invalid')}).status_code == 422
        assert client.post('/api/meetings', files={'file':('test.vtt', SAMPLE)}, data={'source_url':'javascript:alert(1)'}).status_code == 422
        assert client.get('/api/meetings/missing').status_code == 404
        assert 'key' not in client.get('/api/config').text.lower()
        assert client.post('/api/chats', json={'meeting_id':'missing'}).status_code == 404


def test_chat_flow_and_origin_protection(tmp_path):
    app = create_app(tmp_path / 'data.sqlite', imports_dir=tmp_path / 'imports', provider=FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        mid = client.post('/api/meetings', files={'file':('test.vtt', SAMPLE)}).json()['meeting']['id']
        app.state.service.index(mid)
        chat = client.post('/api/chats', json={'meeting_id':mid}).json()
        reply = client.post('/api/chats/' + chat['id'] + '/messages', json={'question':'lexical'})
        assert reply.status_code == 200
        assert reply.json()['citations'][0]['meeting_id'] == mid
        assert len(client.get('/api/chats/' + chat['id']).json()['messages']) == 2
        assert client.post('/api/chats', json={}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.post('/api/search', json={'query':'lexical','meeting_id':mid}).status_code == 200
        assert client.post('/api/search', json={'query':'lexical'}, headers={'Origin':'https://evil.example'}).status_code == 403
        assert client.get('/api/search?q=lexical').status_code == 405


def test_delete_removes_meeting_data_and_scoped_chats_but_keeps_other_history(tmp_path):
    app = create_app(tmp_path / 'data.sqlite', imports_dir=tmp_path / 'imports', provider=FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        mid = client.post('/api/meetings', files={'file':('a.vtt', SAMPLE)}).json()['meeting']['id']
        other = client.post('/api/meetings', files={'file':('b.vtt', SAMPLE.replace(b'Semantic', b'Security'))}).json()['meeting']['id']
        scoped = client.post('/api/chats', json={'meeting_id':mid}).json()['id']
        global_chat = client.post('/api/chats', json={}).json()['id']
        other_chat = client.post('/api/chats', json={'meeting_id':other}).json()['id']
        store = app.state.store
        citation = dict(number=1, meeting_id=mid, title='A', text='Private transcript', chunk_id=1, start=7, end=15, cue_start=0, cue_end=1)
        store.save_turn(scoped, 'Pregunta', 'Respuesta [1]', [citation], {})
        store.save_turn(global_chat, 'Pregunta global', 'Respuesta histórica [1]', [citation], {})
        store.record_usage('chat', 'cheap-chat', {'cost':.01}, owner=hashlib.sha256(b'sk-or-v1-test-key-for-existing-tests').hexdigest())
        assert client.delete('/api/meetings/' + mid, headers={'Origin':'https://evil.example'}).status_code == 403
        result = client.delete('/api/meetings/' + mid)
        assert result.status_code == 200
        assert result.json()['deleted_chat_ids'] == [scoped]
        assert [m['id'] for m in client.get('/api/meetings').json()] == [other]
        assert client.get('/api/meetings/' + mid).status_code == 404
        assert client.get('/api/meetings/' + mid + '/original').status_code == 404
        assert client.get('/api/chats/' + scoped).status_code == 404
        assert client.get('/api/chats/' + other_chat).status_code == 200
        assert not store.chunks(mid)
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM cues WHERE meeting_id=?', (mid,)).fetchone()[0] == 0
            assert db.execute('SELECT COUNT(*) FROM search_index').fetchone()[0] == 1
        history = client.get('/api/chats/' + global_chat).json()['messages']
        assert history[1]['content'] == 'Respuesta histórica [1]'
        assert history[1]['citations'][0]['deleted'] is True
        assert 'text' not in history[1]['citations'][0]
        assert client.get('/api/config').json()['costs']['total'] == .01
        assert client.delete('/api/meetings/' + mid).status_code == 404


def test_deleted_startup_import_stays_deleted_and_can_be_uploaded_explicitly(tmp_path):
    folder = tmp_path / 'imports'
    folder.mkdir()
    (folder / 'initial.vtt').write_bytes(SAMPLE)
    path = tmp_path / 'data.sqlite'
    with TestClient(create_app(path, imports_dir=folder, provider=FakeProvider())) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        mid = client.get('/api/meetings').json()[0]['id']
        assert client.delete('/api/meetings/' + mid).status_code == 200
    with TestClient(create_app(path, imports_dir=folder, provider=FakeProvider())) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        assert client.get('/api/meetings').json() == []
        uploaded = client.post('/api/meetings', files={'file':('initial.vtt', SAMPLE)})
        assert uploaded.json()['created'] is True
        assert uploaded.json()['meeting']['id'] != mid
    with TestClient(create_app(path, imports_dir=folder, provider=FakeProvider())) as client:
        assert len(client.get('/api/meetings').json()) == 1


@pytest.mark.parametrize('scoped', [True, False])
def test_delete_chat_removes_its_messages_and_preserves_archive_and_other_chats(tmp_path, scoped):
    path = tmp_path / 'data.sqlite'
    imports = tmp_path / 'imports'
    app = create_app(path, imports_dir=imports, provider=FakeProvider())
    with TestClient(app) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        mid = client.post('/api/meetings', files={'file':('test.vtt', SAMPLE)}).json()['meeting']['id']
        chat = client.post('/api/chats', json={'meeting_id':mid if scoped else None}).json()['id']
        other = client.post('/api/chats', json={}).json()['id']
        store = app.state.store
        store.save_turn(chat, 'Mi pregunta', 'Mi respuesta', [], {})
        store.save_turn(other, 'Otra pregunta', 'Otra respuesta', [], {})
        store.record_usage('chat', 'cheap-chat', {'cost':.01}, owner=hashlib.sha256(b'sk-or-v1-test-key-for-existing-tests').hexdigest())
        assert client.delete('/api/chats/' + chat, headers={'Origin':'https://evil.example'}).status_code == 403
        assert len(client.get('/api/chats/' + chat).json()['messages']) == 2
        response = client.delete('/api/chats/' + chat)
        assert response.status_code == 200
        assert response.json()['deleted'] is True
        assert [c['id'] for c in client.get('/api/chats').json()] == [other]
        assert client.get('/api/chats/' + chat).status_code == 404
        assert client.delete('/api/chats/' + chat).status_code == 404
        assert client.post('/api/chats/' + chat + '/messages', json={'question':'Hola'}).status_code == 404
        assert len(client.get('/api/chats/' + other).json()['messages']) == 2
        assert client.get('/api/meetings/' + mid + '/original').content == SAMPLE
        assert store.chunks(mid)
        assert client.get('/api/config').json()['costs']['total'] == .01
        with store.connect() as db:
            assert db.execute('SELECT COUNT(*) FROM messages WHERE chat_id=?', (chat,)).fetchone()[0] == 0
    with TestClient(create_app(path, imports_dir=imports, provider=FakeProvider())) as client:
        assert client.post("/api/credentials", json={"key":"sk-or-v1-test-key-for-existing-tests"}).status_code == 200
        assert client.get('/api/chats/' + chat).status_code == 404
        assert client.get('/api/meetings/' + mid).status_code == 200
