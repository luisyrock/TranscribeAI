# TranscribeAI

Archivo local de reuniones: carga transcripciones `.vtt`, busca fragmentos y conversa con ellas. Las citas abren la transcripción en el tramo original con hablante y marca de tiempo. La app, los VTT originales, las intervenciones, el índice y los chats viven en el backend.

## Arrancar

Necesitas Docker con Compose y una clave de OpenRouter con saldo. Clona este repositorio y entra en su carpeta antes de ejecutar los comandos.

```sh
cp .env.example .env
# Ajusta el puerto, modelos o presupuesto si lo necesitas
mkdir -p imports
docker compose up -d --build
```

Abre [TranscribeAI](http://127.0.0.1:8897) e introduce tu propia clave de OpenRouter. Se valida con [la API de claves de OpenRouter](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key) antes de conectar. La instalación comienza con el archivo vacío. Puedes probar la carga con [examples/demo.vtt](examples/demo.vtt), una reunión ficticia sin datos personales; su indexación y las consultas usan tu saldo de OpenRouter.

El puerto se publica solo en `127.0.0.1`. Cada navegador tiene su propia sesión y clave, y debe conectarse antes de acceder al archivo. El archivo local de reuniones y chats es común a las sesiones conectadas; este cambio no añade cuentas ni separación de documentos por persona. Para publicarla como servicio multiusuario hacen falta identidad, permisos y HTTPS.

Las claves permanecen únicamente en memoria del backend durante un máximo de ocho horas; no se guardan en la base de datos, localStorage ni en las respuestas. Una cookie HttpOnly y SameSite=Strict contiene solo un identificador aleatorio. Puedes **Cambiar clave** o **Desconectar** en la barra lateral. Al desconectarte, caducar la sesión o reiniciar Docker se solicita de nuevo. Las peticiones ya enviadas a OpenRouter pueden terminar; se detienen los siguientes lotes de indexación y las llamadas pendientes. Las claves de `.env` no se utilizan.

## Usarla

1. Pulsa **Añadir VTT**. Puedes seleccionar o arrastrar varios archivos; hasta 10 MB por archivo. Para uno solo puedes indicar título, fecha y enlace a Teams u otro origen. El VTT normalmente no contiene la fecha de la reunión, así que la fecha se deja vacía si no la indicas.
2. Espera el punto verde del índice semántico. Mientras se prepara puedes leer las intervenciones; si falla, la app conserva el archivo y ofrece **Reintentar índice**. La búsqueda por palabras sigue disponible.
3. Escoge una reunión o **Todas las reuniones** y pregunta en español, aunque la transcripción esté en inglés. Cambiar el ámbito inicia un chat nuevo. Los chats anteriores aparecen en la barra lateral.
4. Pulsa una cita numérica o una fila de **Fuentes** para ver el tramo resaltado. Usa **Buscar fragmentos** para localizar conceptos sin generar una respuesta de chat.

Los archivos repetidos se detectan por su contenido SHA-256. Puedes volver a cargarlos sin duplicar reuniones. También puedes poner más `.vtt` en `imports/` y ejecutar `docker compose restart`; la importación inicial ocurre al arrancar y la indexación espera a que conectes tu clave.

Para eliminar una reunión, pulsa su papelera en la barra lateral y confirma **Eliminar reunión**. Se borran el VTT guardado, las intervenciones, el índice y los chats dedicados a esa reunión. Los chats generales conservan sus respuestas históricas; las fuentes afectadas quedan marcadas como eliminadas y ya no incluyen los fragmentos originales. El registro de costes se conserva.

El archivo original de tu equipo no se borra. Si estaba en `imports/`, una marca por su hash evita que reaparezca al reiniciar Docker. Puedes volver a subirlo explícitamente desde **Añadir VTT** para incorporarlo de nuevo.

Para eliminar un chat, pulsa la papelera junto a su título en **Chats recientes** y confirma **Eliminar chat**. Se borran ese chat y sus mensajes; las reuniones, los demás chats y el registro de costes se conservan. Si era el chat abierto, la app vuelve a una conversación nueva en el mismo ámbito.

## OpenRouter y costes

Modelos predeterminados:

| Uso | Modelo | Tarifa de referencia por millón de tokens |
| --- | --- | --- |
| Respuestas | `google/gemini-2.5-flash-lite` | US$ 0,10 entrada / 0,40 salida |
| Búsqueda semántica | `baai/bge-m3` | US$ 0,01 entrada |

Tarifas consultadas en el catálogo de OpenRouter el 7 de octubre de 2026; pueden cambiar. La app registra el coste reportado por el proveedor. Cuando no lo reporta, estima con las tarifas de `.env` y lo indica en la respuesta. El contador diario usa UTC. Las embeddings del archivo se calculan una vez y quedan guardadas; cada búsqueda semántica calcula la embedding de la consulta.

`DAILY_BUDGET_USD=1.00` aplica el límite por clave y detiene nuevas llamadas cuando el gasto registrado más una estimación conservadora de la siguiente solicitud excede el límite. Es un control local, no un límite de facturación de la cuenta de OpenRouter; no incluye otras apps ni cargos de solicitudes fallidas que el proveedor no reporte. Puedes ajustar el presupuesto en `.env` y ejecutar `docker compose up -d`. No hay cambios automáticos a otros modelos de pago.

Para cambiar modelos, ajusta `CHAT_MODEL` o `EMBEDDING_MODEL` y sus tarifas `*_USD_PER_M` en `.env`. Al cambiar el modelo de embeddings, las reuniones quedan pendientes y se reindexan cuando alguien conecta su clave; no se mezclan vectores de modelos distintos.

El texto necesario se envía a OpenRouter para embeddings y respuestas. La clave se usa solamente en el backend; `.env`, `imports/` y las bases locales están excluidos de Git y del contexto de compilación de Docker.

## Datos y mantenimiento

Los datos persisten en el volumen de Compose `transcribeai_data`, incluso después de `docker compose down`. Docker añade el nombre del proyecto como prefijo al nombre del volumen. No uses `down -v` si quieres conservarlos.

```sh
docker compose ps
docker compose logs --tail 50 app
docker compose restart
docker compose down
```

Copia consistente de la base, con VTT originales, índices y chats, mientras la app está activa:

```sh
docker compose exec app python -m app.backup /data/backups/archive-backup.sqlite
docker compose cp app:/data/backups/archive-backup.sqlite ./archive-backup.sqlite
```

Usa un nombre nuevo para cada copia. La copia contiene las transcripciones; guárdala en una ubicación privada. Restauración: crea un volumen nuevo con ese archivo como `transcribeai.sqlite`, propiedad del UID `10001`, y configura ese volumen en Compose antes de arrancar. Evita copiar sobre una base activa y sus archivos WAL.

## Desarrollo y verificación

```sh
uv venv --python 3.13
uv pip install -r backend/requirements-dev.txt
.venv/bin/python -m pytest -q
cd frontend
npm ci
npm run build
```

Python 3.13 y Node.js 22 son las versiones usadas en Docker y CI. Las pruebas usan proveedores simulados, no necesitan una clave real ni generan costes. [CONTRIBUTING.md](CONTRIBUTING.md) incluye el arranque para desarrollo y la comprobación del contenedor.

GitHub Actions ejecuta las pruebas de backend, la compilación TypeScript/Vite y una prueba de arranque Docker en cada push y pull request. El flujo tiene permisos de lectura y no requiere secretos de GitHub. Dependabot propone actualizaciones semanales de dependencias y acciones.

El contenedor ejecuta un solo worker. SQLite FTS5 y similitud coseno bastan para un archivo personal; para cientos de miles de fragmentos conviene migrar la recuperación vectorial a pgvector/Qdrant. El frontend usa React, TypeScript y Markdown; FastAPI gestiona ingestión, trabajos, recuperación, chats y OpenRouter. Se reutilizan estas bibliotecas en lugar de una segunda aplicación RAG para mantener el vínculo directo entre cada cita y los bloques VTT.

Los resúmenes largos usan hasta 30 fragmentos distribuidos en el tiempo y avisan de su cobertura parcial. Las respuestas pueden contener errores del modelo; las citas permiten contrastarlas. Esta versión no se conecta automáticamente a Teams ni a GitHub/Jira/Confluence.

## Licencia

TranscribeAI se publica bajo una [licencia personalizada de uso educativo](LICENSE). Permite estudiar el código y ejecutar la app localmente con fines educativos no comerciales. Las copias locales se permiten únicamente en la medida necesaria para ese uso.

No se autoriza reproducir la app para su distribución, republicarla, comercializarla ni ofrecerla como servicio. Se requiere autorización previa y escrita de `luisyrock` para esos usos. Las licencias de las dependencias conservan sus propios términos. Al estar alojado en un repositorio público, se respetan los derechos de visualización y fork dentro de GitHub previstos en sus condiciones de servicio.
