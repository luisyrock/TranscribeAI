# Seguridad y privacidad

Esta versión está diseñada para uso local. Compose publica el puerto en `127.0.0.1`; el backend acepta hosts locales y rechaza orígenes distintos en operaciones que modifican datos.

## Credenciales y datos

- Cada sesión necesita una clave válida de OpenRouter. La clave permanece en memoria del backend durante un máximo de ocho horas. Reiniciar el servidor invalida las sesiones.
- La cookie HttpOnly y SameSite=Strict contiene un identificador aleatorio. Usa Secure cuando la conexión es HTTPS. No contiene la clave.
- La base SQLite conserva VTT originales, textos, índices, chats y costes. Los backups contienen esa misma información. Trátalos como documentos privados.
- El registro de costes identifica una clave por su hash SHA-256. No guarda la clave original.
- Los fragmentos y consultas necesarios para embeddings y respuestas se envían a OpenRouter y a sus proveedores. Comprueba sus condiciones antes de cargar contenido confidencial.
- Las sesiones comparten reuniones y chats. Una clave de OpenRouter habilita el acceso a todo el archivo local; no representa una cuenta con documentos privados.
- El presupuesto de la app controla las llamadas registradas localmente. Configura también límites de gasto en OpenRouter si los necesitas.

## Compartir una instalación

Antes de exponerla en Internet, implementa identidad de usuarios, autorización por documento y chat, HTTPS, límites de solicitudes y una política de retención. La validación de una clave de OpenRouter no sustituye esos controles. Conserva un único worker con el almacenamiento y las sesiones actuales.

## Informar de una vulnerabilidad

Usa un canal privado con el responsable del repositorio. Si el repositorio tiene habilitado el reporte privado de vulnerabilidades de GitHub, puedes usarlo desde la pestaña Security. Evita publicar claves, transcripciones reales o bases de datos en issues. Si una clave se expone, revócala en OpenRouter y genera otra.
