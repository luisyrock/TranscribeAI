import json
import hashlib
import math
import os
import threading
import httpx


class ProviderError(Exception):
    pass


class Provider:
    def __init__(self, store, key=None, budget=None, transport=None):
        self.store = store
        self.key = key or ''
        self.owner = hashlib.sha256(self.key.encode()).hexdigest() if self.key else None
        self.chat_model = os.getenv('CHAT_MODEL', 'google/gemini-2.5-flash-lite')
        self.embedding_model = os.getenv('EMBEDDING_MODEL', 'baai/bge-m3')
        self.budget = float(budget if budget is not None else os.getenv('DAILY_BUDGET_USD', '1'))
        self.transport = transport
        self.lock = threading.Lock()
        self.chat_input_price = float(os.getenv('CHAT_INPUT_USD_PER_M', '.10')) / 1_000_000
        self.chat_output_price = float(os.getenv('CHAT_OUTPUT_USD_PER_M', '.40')) / 1_000_000
        self.embedding_price = float(os.getenv('EMBEDDING_USD_PER_M', '.01')) / 1_000_000

    def validate_key(self):
        try:
            with httpx.Client(timeout=httpx.Timeout(20, connect=10), transport=self.transport) as client:
                response = client.get('https://openrouter.ai/api/v1/key', headers={'Authorization':'Bearer ' + self.key})
            if response.status_code == 401:
                raise ProviderError('OpenRouter rechazó la clave. Revisa que la hayas copiado completa.')
            if response.status_code != 200:
                raise ProviderError('No se pudo validar la clave en OpenRouter. Inténtalo de nuevo.')
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get('data'), dict) or 'error' in result:
                raise ProviderError('OpenRouter devolvió una validación con un formato inválido.')
            if result['data'].get('is_management_key') or result['data'].get('is_provisioning_key'):
                raise ProviderError('Introduce una clave de uso de modelos, no una clave de administración.')
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError('No se pudo conectar con OpenRouter para validar la clave.') from exc

    def request(self, endpoint, payload, operation):
        if not self.key:
            raise ProviderError('Conecta tu clave de OpenRouter para continuar.')
        text_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
        input_price = self.embedding_price if operation == 'embedding' else self.chat_input_price
        reservation = text_bytes * input_price + (1600 * self.chat_output_price if operation == 'chat' else 0)
        with self.lock:
            expired = getattr(self, 'is_expired', lambda:False)()
            if expired and getattr(self, 'stop_event', None):
                self.stop_event.set()
            if expired or (getattr(self, 'stop_event', None) and self.stop_event.is_set()):
                raise ProviderError('La sesión se desconectó. Conecta tu clave de OpenRouter para continuar.')
            if self.store.costs(self.owner)['today'] + reservation > self.budget:
                raise ProviderError('Se alcanzó el presupuesto diario configurado. Puedes ajustarlo en .env.')
            try:
                with httpx.Client(timeout=httpx.Timeout(90, connect=15), transport=self.transport) as client:
                    response = client.post('https://openrouter.ai/api/v1/' + endpoint, json=payload,
                                           headers={'Authorization':'Bearer ' + self.key, 'X-Title':'TranscribeAI local'})
                if response.status_code != 200:
                    errors = {401:'OpenRouter rechazó la clave configurada.',402:'No hay saldo suficiente en OpenRouter.',429:'OpenRouter está limitando las solicitudes. Inténtalo más tarde.'}
                    raise ProviderError(errors.get(response.status_code, f'OpenRouter devolvió un error ({response.status_code}). Inténtalo de nuevo.'))
                result = response.json()
                if not isinstance(result, dict):
                    raise ProviderError('OpenRouter devolvió datos con un formato inválido.')
                if 'error' in result:
                    raise ProviderError('OpenRouter no pudo completar la solicitud.')
            except (httpx.HTTPError, ValueError) as exc:
                raise ProviderError('No se pudo obtener una respuesta de OpenRouter. Revisa la conexión y reintenta.') from exc
            raw = result.get('usage') or {}
            tokens_in = raw.get('prompt_tokens', raw.get('input_tokens', raw.get('total_tokens', 0)))
            tokens_out = raw.get('completion_tokens', 0)
            cost = raw.get('cost')
            usage = {'input_tokens':tokens_in, 'output_tokens':tokens_out, 'cost':float(cost if cost is not None else tokens_in * input_price + tokens_out * self.chat_output_price), 'estimated':cost is None, 'model':payload['model']}
            self.store.record_usage(operation, payload['model'], usage, owner=self.owner)
            return result, usage

    def embed(self, texts):
        if not texts:
            return [], {}
        result, usage = self.request('embeddings', {'model':self.embedding_model, 'input':texts}, 'embedding')
        data = sorted(result.get('data', []), key=lambda r:r.get('index', 0))
        vectors = [row.get('embedding') for row in data]
        if len(vectors) != len(texts) or any(not isinstance(v, list) or not v or any(not isinstance(x, (int,float)) or not math.isfinite(x) for x in v) for v in vectors):
            raise ProviderError('OpenRouter devolvió vectores incompletos. Puedes reintentar la indexación.')
        return vectors, usage

    def complete(self, messages):
        result, usage = self.request('chat/completions', {'model':self.chat_model, 'messages':messages, 'temperature':.15, 'max_tokens':1600, 'response_format':{'type':'json_object'}}, 'chat')
        try:
            content = result['choices'][0]['message']['content']
            if not isinstance(content, str) or not content:
                raise ValueError()
            return content, usage
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError('OpenRouter devolvió una respuesta vacía. Inténtalo de nuevo.') from exc
