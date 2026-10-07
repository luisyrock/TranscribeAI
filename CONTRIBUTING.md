# Desarrollo

## Preparar el entorno

Necesitas Python 3.13, Node.js 22 y Docker con Compose para comprobar el contenedor. Los ejemplos siguientes usan `venv`; también puedes usar `uv` como explica el README.

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest -q
cd frontend
npm ci
npm run build
```

Las pruebas crean bases temporales y usan HTTP simulado para OpenRouter. No añadas claves reales ni transcripciones de reuniones a los fixtures.

## Ejecutar durante el desarrollo

Desde la raíz del repositorio, en una terminal:

```sh
mkdir -p .data imports
DATABASE_PATH="$PWD/.data/transcribeai.sqlite" IMPORTS_DIR="$PWD/imports" \
  PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:create_app \
  --factory --host 127.0.0.1 --port 8000 --reload
```

En otra terminal:

```sh
cd frontend
npm run dev
```

Abre la dirección que muestra Vite e introduce tu propia clave. Vite redirige `/api` al backend local. Los ajustes de `.env` se cargan mediante Compose; en este modo debes exportar los ajustes que quieras cambiar antes de iniciar el backend.

## Comprobar Docker

```sh
docker build -t transcribeai:check .
python3 scripts/smoke_docker.py transcribeai:check
```

La comprobación crea un contenedor temporal con un puerto local libre, sin montar archivos ni volúmenes existentes. Verifica salud, frontend, configuración sin sesión, rechazo de acceso al archivo, validación de credenciales y base de datos vacía. Lo elimina al terminar. No llama a OpenRouter ni necesita claves.

## Proponer cambios

Describe el problema, el comportamiento resultante y cómo lo verificaste. Mantén el backend como fuente de verdad de reuniones, chats y costes. Las credenciales permanecen solo en memoria del servidor y no deben aparecer en logs, respuestas o persistencia del navegador.

Antes de publicar cambios, revisa `git diff --cached` y `git status --short`. Mantén fuera del repositorio `.env`, reuniones reales, bases, backups y capturas con información privada. Usa el ejemplo ficticio para reproducir problemas. Revisa también [SECURITY.md](SECURITY.md).
