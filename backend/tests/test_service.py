import json
import pytest
import httpx
from app.store import Store
from app.provider import Provider, ProviderError
from app.service import Service
from test_core import SAMPLE


class FakeProvider:
    chat_model = 'cheap-chat'
    embedding_model = 'multilingual'
    def __init__(self):
        self.calls = []
        self.answer = 'Se habló de búsqueda léxica [1].'
    def validate_key(self):
        pass
    def embed(self, texts):
        self.calls.append(('embed', texts))
        return [[1.0, 0.0] for _ in texts], {}
    def complete(self, messages):
        self.calls.append(('chat', messages))
        return json.dumps({'answer': self.answer}), {'cost': .0001, 'estimated': False}


def test_ingest_index_grounded_chat_and_persistence(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, created = service.ingest(SAMPLE, 'sample.vtt', 'Arquitectura')
    assert created
    service.index(item['id'])
    assert store.meeting(item['id'])['status'] == 'ready'
    chat = store.create_chat(item['id'])
    answer = service.ask(chat['id'], '¿Qué se dijo de la búsqueda?')
    assert answer['citations'][0]['meeting_id'] == item['id']
    assert answer['citations'][0]['start'] == 7.493
    assert len(Store(store.path).chat(chat['id'])['messages']) == 2
    service.ask(chat['id'], '¿Y quién lo dijo?')
    context = provider.calls[-1][1]
    assert any(m['role'] == 'assistant' for m in context)
    assert '¿Qué se dijo' in str(context)


def test_reject_invented_source_numbers(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt', 'A')
    service.index(item['id'])
    chat = store.create_chat(item['id'])
    provider.answer = 'Una decisión [999].'
    with pytest.raises(ProviderError):
        service.ask(chat['id'], 'lexical')
    assert not store.chat(chat['id'])['messages']


def test_empty_archive_abstains_without_paid_call(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    result = service.ask(store.create_chat()['id'], '¿Qué se decidió?')
    assert not result['citations']
    assert not provider.calls


def test_provider_records_usage_and_sanitizes_errors(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    def respond(request):
        if request.url.path.endswith('embeddings'):
            return httpx.Response(200, json={'data':[{'index':0,'embedding':[1,0]}], 'usage':{'prompt_tokens':5,'total_tokens':5,'cost':.00001}})
        return httpx.Response(401, json={'error':{'message':'PRIVATE-KEY-NEVER-EXPOSE'}})
    provider = Provider(store, key='PRIVATE-KEY-NEVER-EXPOSE', transport=httpx.MockTransport(respond))
    vectors, usage = provider.embed(['hola'])
    assert vectors == [[1,0]]
    assert store.costs()['total'] == .00001
    with pytest.raises(ProviderError) as error:
        provider.complete([{'role':'user','content':'hola'}])
    assert 'PRIVATE-KEY' not in str(error.value)


def test_budget_stops_request_before_network(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    def respond(request):
        pytest.fail('El presupuesto agotado no debe llamar al proveedor')
    provider = Provider(store, key='test', budget=0, transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderError, match='presupuesto'):
        provider.embed(['hola'])


def test_malformed_success_is_sanitized(tmp_path):
    provider = Provider(Store(tmp_path / 'data.sqlite'), key='test', transport=httpx.MockTransport(lambda r:httpx.Response(200, json=[])))
    with pytest.raises(ProviderError):
        provider.embed(['hola'])


def test_index_failure_keeps_lexical_and_retry_recovers(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt', 'A')
    original_embed = provider.embed
    def fail(texts):
        raise ProviderError('Proveedor temporalmente indisponible.')
    provider.embed = fail
    service.index(item['id'])
    assert store.meeting(item['id'])['status'] == 'error'
    assert store.original(item['id']) == SAMPLE
    found, warning = service.search('lexical', item['id'])
    assert found and warning
    provider.embed = original_embed
    service.index(item['id'])
    assert store.meeting(item['id'])['status'] == 'ready'
    count = len(provider.calls)
    service.index(item['id'])
    assert len(provider.calls) == count


def test_grouped_citations_are_all_validated_and_expand(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt', 'A')
    service.index(item['id'])
    chat = store.create_chat(item['id'])
    provider.answer = 'La búsqueda [1, 999] y otra cita [1].'
    with pytest.raises(ProviderError):
        service.ask(chat['id'], 'lexical')
    provider.answer = 'La búsqueda [1, 1].'
    result = service.ask(chat['id'], 'lexical')
    assert result['answer'] == 'La búsqueda [1][1].'
    assert len(result['citations']) == 1


def test_timestamp_citations_only_resolve_inside_retrieved_sources(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt', 'A')
    service.index(item['id'])
    chat = store.create_chat(item['id'])
    provider.answer = 'Ana propuso búsqueda [00:07, 00:11].'
    result = service.ask(chat['id'], 'lexical')
    assert result['answer'] == 'Ana propuso búsqueda [1][1].'
    assert len(result['citations']) == 1
    provider.answer = 'Otra cosa [59:59] y una fuente válida [1].'
    with pytest.raises(ProviderError):
        service.ask(chat['id'], 'lexical')


def test_delete_during_index_does_not_apply_old_vectors_to_reuploaded_chunks(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt')
    replacement = []
    def embed_during_delete(texts):
        store.delete_meeting(item['id'])
        replacement.append(service.ingest(SAMPLE, 'again.vtt')[0])
        return [[1, 0] for _ in texts], {}
    provider.embed = embed_during_delete
    service.index(item['id'])
    chunks = store.chunks(replacement[0]['id'])
    assert chunks and all(c['embedding'] is None for c in chunks)
    assert store.meeting(replacement[0]['id'])['status'] == 'pending'


def test_chat_response_finishing_after_delete_marks_sources_unavailable(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt')
    chat = store.create_chat()
    original_complete = provider.complete
    def complete_during_delete(messages):
        store.delete_meeting(item['id'])
        return original_complete(messages)
    provider.complete = complete_during_delete
    result = service.ask(chat['id'], 'Resumen')
    assert result['citations'][0]['deleted'] is True
    assert 'text' not in result['citations'][0]
    assert store.chat(chat['id'])['messages'][1]['citations'][0]['deleted'] is True


def test_deleted_scoped_chat_rejects_inflight_answer_without_partial_turn(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt')
    chat = store.create_chat(item['id'])
    original_complete = provider.complete
    def complete_during_delete(messages):
        store.delete_meeting(item['id'])
        return original_complete(messages)
    provider.complete = complete_during_delete
    with pytest.raises(KeyError, match='Chat no encontrado'):
        service.ask(chat['id'], 'Resumen')
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0


def test_chat_deleted_during_response_cannot_be_recreated_by_late_answer(tmp_path):
    store = Store(tmp_path / 'data.sqlite')
    provider = FakeProvider()
    service = Service(store, provider)
    item, _ = service.ingest(SAMPLE, 'a.vtt')
    chat = store.create_chat(item['id'])
    original_complete = provider.complete
    def complete_during_delete(messages):
        store.delete_chat(chat['id'])
        return original_complete(messages)
    provider.complete = complete_during_delete
    with pytest.raises(KeyError, match='Chat no encontrado'):
        service.ask(chat['id'], 'Resumen')
    assert store.chats() == []
    assert store.original(item['id']) == SAMPLE
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 0
