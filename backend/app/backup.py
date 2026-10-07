"""Consistent SQLite snapshot, including original VTTs and chats."""
import os
import sqlite3
import sys
from pathlib import Path


def backup(destination):
    source = Path(os.getenv('DATABASE_PATH', '/data/transcribeai.sqlite')).resolve()
    target = Path(destination).resolve()
    if source == target or target.exists():
        raise ValueError('El destino debe ser un archivo nuevo, distinto de la base activa.')
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as original, sqlite3.connect(target) as snapshot:
        original.backup(snapshot)
    target.chmod(0o600)
    print('Copia consistente creada.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python -m app.backup /data/backups/nombre.sqlite')
    backup(sys.argv[1])
