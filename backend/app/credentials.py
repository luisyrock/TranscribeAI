import hashlib
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from app.service import Service

COOKIE = 'transcribeai_session'
LIFETIME = 8 * 60 * 60


@dataclass
class CredentialSession:
    service: Service
    expires: float
    stopped: threading.Event = field(default_factory=threading.Event)


class Credentials:
    """Keys live only in backend memory; cookies contain an opaque random ID."""
    def __init__(self, store, provider_factory, clock=time.monotonic):
        self.store, self.factory, self.clock = store, provider_factory, clock
        self.sessions, self.budget_locks = {}, {}
        self.lock = threading.Lock()

    def _expire(self):
        for token, session in list(self.sessions.items()):
            if session.expires <= self.clock():
                session.stopped.set()
                del self.sessions[token]

    def get(self, token):
        with self.lock:
            self._expire()
            return self.sessions.get(token)

    def purge_expired(self):
        with self.lock:
            self._expire()

    def connect(self, key, old_token=None):
        key = key.strip()
        if not re.fullmatch(r'sk-or-v1-[A-Za-z0-9_-]{12,500}', key):
            raise ValueError('Introduce una clave de OpenRouter válida, que empiece por sk-or-v1-.')
        provider = self.factory(key)
        provider.validate_key()
        owner = hashlib.sha256(key.encode()).hexdigest()
        with self.lock:
            self._expire()
            previous = self.sessions.pop(old_token, None)
            if previous:
                previous.stopped.set()
            provider.owner = owner
            provider.lock = self.budget_locks.setdefault(owner, threading.Lock())
            token = secrets.token_urlsafe(32)
            session = CredentialSession(Service(self.store, provider), self.clock() + LIFETIME)
            provider.stop_event = session.stopped
            provider.is_expired = lambda deadline=session.expires:self.clock() >= deadline
            self.sessions[token] = session
            return token, session

    def disconnect(self, token):
        with self.lock:
            session = self.sessions.pop(token, None)
            if session:
                session.stopped.set()
