import asyncio
import copy
import os
from contextlib import asynccontextmanager
from datetime import date as Date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, UploadFile, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, SecretStr
from app.provider import Provider, ProviderError
from app.service import Service
from app.store import Store
from app.credentials import Credentials, COOKIE, LIFETIME


class CredentialsBody(BaseModel):
    key: SecretStr


class ChatBody(BaseModel):
    meeting_id: str | None = None


class QuestionBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    meeting_id: str | None = None


def create_app(db_path=None, imports_dir=None, provider=None, provider_factory=None):
    store = Store(db_path or os.getenv('DATABASE_PATH', '/data/transcribeai.sqlite'))
    provider = provider or Provider(store)
    service = Service(store, provider)
    factory = provider_factory or ((lambda key:copy.copy(provider)) if getattr(provider, 'validate_key', None) and not isinstance(provider, Provider) else (lambda key:Provider(store,key=key)))
    credentials = Credentials(store, factory)
    jobs, chat_locks = {}, {}

    def schedule(mid, session):
        old = jobs.get(mid)
        if old and old[0] is session and not old[1].done():
            return
        async def run():
            if old and not old[1].done():
                await asyncio.gather(old[1], return_exceptions=True)
            if not session.stopped.is_set():
                await asyncio.to_thread(session.service.index, mid, session.stopped)
        task = asyncio.create_task(run())
        jobs[mid] = (session, task)
        def finished(done):
            current = jobs.get(mid)
            if current and current[1] is done:
                del jobs[mid]
        task.add_done_callback(finished)

    @asynccontextmanager
    async def lifespan(app):
        folder = Path(imports_dir or os.getenv('IMPORTS_DIR', '/imports'))
        if folder.exists():
            for file in sorted(folder.glob('*.vtt')):
                try:
                    if file.stat().st_size <= 10 * 1024 * 1024:
                        service.ingest(file.read_bytes(), file.name, automatic=True)
                except ValueError:
                    print('No se pudo importar un archivo inicial VTT. Revisa su formato.', flush=True)
        for m in store.list_meetings():
            # Changing the embedding model also requires a fresh index.
            mismatched = any(c['embedding_model'] != provider.embedding_model for c in store.chunks(m['id']))
            if m['status'] == 'indexing' or (m['status'] == 'ready' and mismatched):
                store.status(m['id'], 'pending')
        async def expire_sessions():
            while True:
                await asyncio.sleep(10)
                credentials.purge_expired()
        cleanup = asyncio.create_task(expire_sessions())
        try:
            yield
        finally:
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)
            if jobs:
                await asyncio.gather(*(job[1] for job in jobs.values()), return_exceptions=True)

    app = FastAPI(title='TranscribeAI', lifespan=lifespan)
    app.state.store, app.state.service, app.state.credentials = store, service, credentials
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost','127.0.0.1','testserver','[::1]'])

    @app.middleware('http')
    async def local_origin(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail':'Origen de solicitud no permitido.'}, status_code=403)
        session = credentials.get(request.cookies.get(COOKIE))
        request.state.session = session
        if request.url.path.startswith('/api/') and request.url.path not in ('/api/health','/api/config','/api/credentials') and not session:
            return JSONResponse({'detail':'Conecta tu clave de OpenRouter para continuar.'}, status_code=401, headers={'Cache-Control':'no-store'})
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if request.url.path == '/api/credentials':
            return JSONResponse({'detail':'Introduce tu clave de OpenRouter en el campo indicado.'}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail':str(exc.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail':str(exc)}, status_code=422)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({'detail':str(exc)}, status_code=502)

    @app.get('/api/health')
    def health():
        return {'status':'ok'}

    @app.get('/api/config')
    def config(request: Request):
        session = request.state.session
        current = session.service.provider if session else provider
        return {'configured':bool(session), 'chat_model':current.chat_model,
                'embedding_model':current.embedding_model, 'daily_budget':getattr(current,'budget', 1),
                'costs':store.costs(current.owner) if session else {'total':0,'today':0,'calls':0}}

    @app.post('/api/credentials')
    async def connect(body: CredentialsBody, request: Request):
        token, session = await asyncio.to_thread(credentials.connect, body.key.get_secret_value(), request.cookies.get(COOKIE))
        for m in store.list_meetings():
            mismatched = any(c['embedding_model'] != session.service.provider.embedding_model for c in store.chunks(m['id']))
            if m['status'] in ('pending','indexing','error') or mismatched:
                schedule(m['id'], session)
        response = JSONResponse({'configured':True})
        response.set_cookie(COOKIE, token, max_age=LIFETIME, httponly=True, samesite='strict', secure=request.url.scheme=='https')
        return response

    @app.delete('/api/credentials')
    def disconnect(request: Request):
        credentials.disconnect(request.cookies.get(COOKIE))
        response = JSONResponse({'configured':False})
        response.delete_cookie(COOKIE, httponly=True, samesite='strict')
        return response

    @app.get('/api/meetings')
    def meetings():
        return store.list_meetings()

    @app.post('/api/meetings')
    async def upload(request: Request, file: UploadFile = File(...), title: str = Form(''), date: str = Form(''), source_url: str = Form('')):
        if date:
            Date.fromisoformat(date)
        if source_url:
            parsed = urlparse(source_url)
            if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username:
                raise ValueError('El enlace de origen debe ser una URL http o https válida.')
        if len(title) > 180 or len(source_url) > 2000:
            raise ValueError('El título o enlace es demasiado largo.')
        data = await file.read(10 * 1024 * 1024 + 1)
        await file.close()
        item, created = service.ingest(data, file.filename or 'upload.vtt', title, date or None, source_url or None)
        if created:
            schedule(item['id'], request.state.session)
        return {'meeting':item, 'created':created}

    @app.get('/api/meetings/{mid}')
    def meeting(mid: str):
        return store.meeting(mid)

    @app.delete('/api/meetings/{mid}')
    def delete_meeting(mid: str):
        return store.delete_meeting(mid)

    @app.get('/api/meetings/{mid}/original')
    def original(mid: str):
        return Response(store.original(mid), media_type='text/vtt', headers={'Content-Disposition':'attachment; filename="transcript.vtt"'})

    @app.post('/api/meetings/{mid}/reindex')
    async def reindex(mid: str, request: Request):
        store.meeting(mid)
        schedule(mid, request.state.session)
        return {'status':'indexing'}

    @app.post('/api/search')
    async def search(body: SearchBody, request: Request):
        q, meeting_id = body.query, body.meeting_id
        if not q.strip() or len(q) > 4000:
            raise ValueError('Escribe una búsqueda de entre 1 y 4000 caracteres.')
        if meeting_id:
            store.meeting(meeting_id)
        results, warning = await asyncio.to_thread(request.state.session.service.search, q, meeting_id)
        return {'results':results, 'warning':warning}

    @app.get('/api/chats')
    def chats():
        return store.chats()

    @app.post('/api/chats')
    def create_chat(body: ChatBody):
        return store.create_chat(body.meeting_id)

    @app.get('/api/chats/{cid}')
    def chat(cid: str):
        return store.chat(cid)

    @app.delete('/api/chats/{cid}')
    def delete_chat(cid: str):
        return store.delete_chat(cid)

    @app.post('/api/chats/{cid}/messages')
    async def ask(cid: str, body: QuestionBody, request: Request):
        lock = chat_locks.setdefault(cid, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(request.state.session.service.ask, cid, body.question)

    frontend = Path(os.getenv('FRONTEND_DIR', '/app/static'))
    if frontend.is_dir():
        app.mount('/assets', StaticFiles(directory=frontend / 'assets'), name='assets')

        @app.get('/')
        def index():
            return FileResponse(frontend / 'index.html')
    return app


# Use a factory so test imports never create the production database.
