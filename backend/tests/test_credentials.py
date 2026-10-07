import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.provider import Provider, ProviderError
from app.store import Store
from app.credentials import Credentials, LIFETIME
from test_core import SAMPLE

A = 'sk-or-v1-' + 'a' * 64
B = 'sk-or-v1-' + 'b' * 64


def factory(store, observed):
    def respond(request):
        key = request.headers['Authorization'].removeprefix('Bearer ')
        if request.url.path.endswith('/key'):
            return httpx.Response(200, json={'data':{'limit_remaining':1}}) if key in (A, B) else httpx.Response(401, json={'error':{'message':key}})
        observed.append(key)
        if request.url.path.endswith('/embeddings'):
            texts = json.loads(request.content)['input']
            return httpx.Response(200, json={'data':[{'index':i,'embedding':[1,0]} for i,_ in enumerate(texts)], 'usage':{'prompt_tokens':5,'cost':.01}})
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"answer":"La búsqueda [1]."}'}}], 'usage':{'prompt_tokens':10,'completion_tokens':5,'cost':.02}})
    return lambda key: Provider(store, key=key, transport=httpx.MockTransport(respond))


def test_environment_key_cannot_bypass_session_and_credentials_never_echo(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY', A)
    calls=[]
    store=Store(tmp_path / 'db.sqlite')
    app=create_app(store.path, imports_dir=tmp_path / 'imports', provider_factory=factory(store,calls))
    with TestClient(app) as client:
        assert client.get('/api/config').json()['configured'] is False
        assert client.get('/api/meetings').status_code == 401
        assert client.post('/api/search',json={'query':'lexical'}).status_code == 401
        assert client.post('/api/credentials',json={'key':A},headers={'Origin':'https://evil.example'}).status_code == 403
        for body in [{'key':''},{'key':'invalid'}, {'key':A * 20}, {'key':[A]}]:
            result=client.post('/api/credentials',json=body)
            assert result.status_code == 422
            assert A not in result.text
        invalid='sk-or-v1-' + 'c' * 64
        result=client.post('/api/credentials',json={'key':invalid})
        assert result.status_code == 502 and invalid not in result.text
        result=client.post('/api/credentials',json={'key':A})
        assert result.status_code == 200 and A not in result.text
        cookie=result.headers['set-cookie']
        assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie
        assert A not in cookie
        assert client.get('/api/meetings').status_code == 200
        assert A not in client.get('/api/config').text
        assert calls == []
        client.delete('/api/credentials')
        assert client.get('/api/config').json()['configured'] is False
        assert client.post('/api/search',json={'query':'hola'}).status_code == 401


def test_two_sessions_use_their_own_key_costs_and_rotation_revokes_old_cookie(tmp_path):
    store=Store(tmp_path / 'db.sqlite')
    observed=[]
    app=create_app(store.path, imports_dir=tmp_path / 'imports', provider_factory=factory(store,observed))
    with TestClient(app) as a, TestClient(app) as b:
        a.post('/api/credentials',json={'key':A})
        old=a.cookies.get('transcribeai_session')
        mid=a.post('/api/meetings',files={'file':('a.vtt',SAMPLE)}).json()['meeting']['id']
        assert b.get('/api/config').json()['configured'] is False
        assert b.post('/api/search',json={'query':'lexical'}).status_code == 401
        b.post('/api/credentials',json={'key':B})
        chat=b.post('/api/chats',json={'meeting_id':mid}).json()['id']
        assert b.post('/api/chats/'+chat+'/messages',json={'question':'Resumen'}).status_code == 200
        assert observed[-1] == B
        assert b.get('/api/config').json()['costs']['total'] == .02
        assert a.get('/api/config').json()['costs']['total'] != .02
        # A second session using B sees the same budget ledger, not a reset.
        a.post('/api/credentials',json={'key':B})
        assert a.get('/api/config').json()['costs']['total'] == .02
        with TestClient(app) as stale:
            stale.cookies.set('transcribeai_session',old)
            assert stale.get('/api/meetings').status_code == 401
        a.delete('/api/credentials')
        assert b.post('/api/search',json={'query':'lexical'}).status_code == 200
        assert observed[-1] == B


def test_restart_requires_reconnecting_and_no_background_paid_import(tmp_path):
    imports=tmp_path/'imports'
    imports.mkdir()
    (imports/'a.vtt').write_bytes(SAMPLE)
    store=Store(tmp_path/'db.sqlite')
    observed=[]
    build=lambda:create_app(store.path, imports_dir=imports, provider_factory=factory(store,observed))
    with TestClient(build()) as client:
        assert observed == []
        client.post('/api/credentials',json={'key':A})
        cookie=client.cookies.get('transcribeai_session')
    assert observed and set(observed) == {A}
    with TestClient(build()) as client:
        count=len(observed)
        client.cookies.set('transcribeai_session',cookie)
        assert client.get('/api/config').json()['configured'] is False
        assert client.get('/api/meetings').status_code == 401
        assert len(observed) == count


def test_provider_without_explicit_key_ignores_environment(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENROUTER_API_KEY',A)
    provider=Provider(Store(tmp_path/'db.sqlite'),transport=httpx.MockTransport(lambda request:pytest.fail('No key means no request')))
    with pytest.raises(ProviderError):
        provider.embed(['hola'])


def test_expired_session_blocks_calls_even_with_remaining_browser_cookie(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    observed=[]
    app=create_app(store.path, imports_dir=tmp_path/'imports', provider_factory=factory(store,observed))
    time=[0]
    app.state.credentials.clock=lambda:time[0]
    with TestClient(app) as client:
        assert client.post('/api/credentials',json={'key':A}).status_code == 200
        time[0]=8*60*60+1
        assert client.get('/api/config').json()['configured'] is False
        assert client.post('/api/search',json={'query':'hola'}).status_code == 401
        assert observed == []


def test_key_budget_survives_new_session_and_invalid_replacement_keeps_connection(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    observed=[]
    app=create_app(store.path, imports_dir=tmp_path/'imports', provider_factory=factory(store,observed))
    with TestClient(app) as a, TestClient(app) as b:
        a.post('/api/credentials',json={'key':A})
        session=app.state.credentials.get(a.cookies.get('transcribeai_session'))
        store.record_usage('chat','cheap',{'cost':1},owner=session.service.provider.owner)
        b.post('/api/credentials',json={'key':A})
        result=b.post('/api/search',json={'query':'hola'})
        assert 'presupuesto' in result.json()['warning']
        assert observed == []
        old=b.cookies.get('transcribeai_session')
        assert b.post('/api/credentials',json={'key':'sk-or-v1-'+ 'c'*64}).status_code == 502
        assert b.cookies.get('transcribeai_session') == old
        assert b.get('/api/config').json()['configured'] is True


def test_background_provider_rejects_expired_session_without_http_lookup(tmp_path):
    store=Store(tmp_path/'db.sqlite')
    observed=[]
    time=[0]
    credentials=Credentials(store,factory(store,observed),clock=lambda:time[0])
    token,session=credentials.connect(A)
    time[0]=LIFETIME+1
    with pytest.raises(ProviderError):
        session.service.provider.embed(['late background work'])
    assert observed == []
    assert session.stopped.is_set()
    credentials.purge_expired()
    assert credentials.sessions == {}
