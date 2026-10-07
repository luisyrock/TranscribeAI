"""Exercise a disposable Docker installation without credentials or private data."""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def request(base, path, *, data=None):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json'} if data is not None else {},
    )
    try:
        response = urllib.request.urlopen(req, timeout=3)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, response.headers, response.read().decode()


def main(image):
    name = 'transcribeai-smoke-' + uuid.uuid4().hex[:12]
    docker('run', '--detach', '--rm', '--name', name,
           '--publish', '127.0.0.1::8000', image)
    try:
        base = 'http://' + docker('port', name, '8000/tcp').splitlines()[0]
        deadline = time.monotonic() + 60
        while True:
            try:
                status, _, body = request(base, '/api/health')
                if status == 200 and json.loads(body) == {'status': 'ok'}:
                    break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('The disposable container did not become healthy.')
            time.sleep(0.5)

        status, _, body = request(base, '/')
        assert status == 200 and 'TranscribeAI' in body, 'Frontend is unavailable'
        status, headers, body = request(base, '/api/config')
        config = json.loads(body)
        assert status == 200 and config['configured'] is False
        assert config['costs'] == {'total': 0, 'today': 0, 'calls': 0}
        assert headers.get('Cache-Control') == 'no-store'
        status, _, _ = request(base, '/api/meetings')
        assert status == 401, 'The archive must require a session'
        status, _, _ = request(base, '/api/credentials', data={'key': ''})
        assert status == 422, 'Empty credentials must be rejected locally'

        counts = docker('exec', name, 'python', '-c',
                        'import sqlite3, os, json; '
                        'db=sqlite3.connect(os.environ["DATABASE_PATH"]); '
                        'print(json.dumps([db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] '
                        'for table in ("meetings", "chats", "usage")]))')
        assert json.loads(counts) == [0, 0, 0], 'A new installation must be empty'
        print('Docker smoke passed: frontend, health, session requirement, empty archive; no provider calls.')
    except Exception:
        print(docker('logs', name), file=sys.stderr)
        raise
    finally:
        docker('stop', '--time', '5', name)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: python scripts/smoke_docker.py IMAGE')
    main(sys.argv[1])
