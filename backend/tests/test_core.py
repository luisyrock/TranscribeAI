from pathlib import Path
import pytest

from app.transcripts import parse_vtt, chunk_cues
from app.store import Store
from app.retrieval import retrieve

SAMPLE = b'''\xef\xbb\xbfWEBVTT\n\ncue-a\n00:00:07.493 --> 00:00:10.293 align:start\n<v Ana>Semantic &amp; lexical\nsearch.</v>\n\ncue-b\n00:00:11.000 --> 00:00:15.100\n<v Luis>Keep the fallback.</v>\n'''


def test_parse_bom_speakers_entities_and_multiline():
    cues = parse_vtt(SAMPLE)
    assert len(cues) == 2
    assert cues[0].speaker == 'Ana'
    assert cues[0].start == 7.493
    assert cues[0].end == 10.293
    assert cues[0].text == 'Semantic & lexical search.'


def test_metadata_blocks_and_minutes_without_hours():
    cues = parse_vtt(b'WEBVTT\n\nNOTE ignore\nmetadata\n\nSTYLE\n::cue {color:red}\n\n00:01.000 --> 00:02.000\nHello\n')
    assert len(cues) == 1
    assert cues[0].speaker is None
    assert cues[0].start == 1


def test_metadata_like_ids_and_multiple_voice_segments():
    cues = parse_vtt(b'WEBVTT\n\nNOTE-123\n00:01.000 --> 00:02.000\n<v Ana>Proposal.</v><v Luis>I disagree.</v>\n\nSTYLE-456\n00:03.000 --> 00:04.000\nKept.\n')
    assert len(cues) == 2
    assert cues[0].speaker == 'Ana / Luis'
    assert 'Ana: Proposal.' in cues[0].text
    assert 'Luis: I disagree.' in cues[0].text
    with pytest.raises(ValueError):
        parse_vtt(b'WEBVTT\n\n99:00.000 --> 99:01.000\nInvalid.')


@pytest.mark.parametrize('data', [b'hello', b'WEBVTT\n', b'WEBVTT\n\n00:04.000 --> 00:01.000\nbad', b'WEBVTT\n\n00:99.000 --> 00:100.000\nbad'])
def test_rejects_invalid_transcripts(data):
    with pytest.raises(ValueError):
        parse_vtt(data)


def test_chunk_preserves_cue_boundaries():
    chunks = chunk_cues(parse_vtt(SAMPLE))
    assert chunks[0].cue_start == 0
    assert chunks[0].cue_end == 1
    assert 'Ana' in chunks[0].text
    assert '00:07' in chunks[0].text


def test_durable_duplicate_import_and_scoped_search(tmp_path):
    path = tmp_path / 'db.sqlite'
    store = Store(path)
    a, created = store.add_meeting('Architecture', 'a.vtt', SAMPLE, parse_vtt(SAMPLE), chunk_cues(parse_vtt(SAMPLE)), None, None)
    duplicate, created_again = store.add_meeting('Duplicate', 'dup.vtt', SAMPLE, parse_vtt(SAMPLE), chunk_cues(parse_vtt(SAMPLE)), None, None)
    assert created and not created_again and a['id'] == duplicate['id']
    other = SAMPLE.replace(b'Semantic', b'Security').replace(b'cue-a', b'cue-x')
    b, _ = store.add_meeting('Other', 'b.vtt', other, parse_vtt(other), chunk_cues(parse_vtt(other)), '2026-10-01', None)
    reopened = Store(path)
    assert len(reopened.list_meetings()) == 2
    assert reopened.meeting(a['id'])['cues'][0]['speaker'] == 'Ana'
    found = retrieve(reopened, None, 'lexical', a['id'], 'test-model')
    assert found and all(x['meeting_id'] == a['id'] for x in found)
    assert not retrieve(reopened, None, 'security', a['id'], 'test-model')


def test_semantic_retrieval_cross_language_and_model_isolation(tmp_path):
    store = Store(tmp_path / 'db.sqlite')
    m, _ = store.add_meeting('Architecture', 'a.vtt', SAMPLE, parse_vtt(SAMPLE), chunk_cues(parse_vtt(SAMPLE)), None, None)
    cid = store.chunks(m['id'])[0]['id']
    store.save_embeddings([cid], [[1.0, 0.0]], 'multilingual')
    found = retrieve(store, [1.0, 0.0], 'b\xc3\xbasqueda'.encode().decode('unicode_escape'), None, 'multilingual')
    assert found[0]['meeting_id'] == m['id']
    assert not retrieve(store, [1.0, 0.0], 'unmatched', None, 'different-model')
