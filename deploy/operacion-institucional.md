# Operación institucional

## Estado de este material

Esta guía prepara la operación institucional **sin declarar una instalación lista para producción**. Desde `arranque-para-el-instituto` el repositorio SÍ tiene un *composition root* real: el comando único `anonimizacion` (`pyproject.toml`, `[project.scripts]`) conecta el portal, el lanzamiento de corridas y PostgreSQL de punta a punta para el modo de operación de un solo médico en una sola máquina -- ver "Instalación base" más abajo. Lo que sigue faltando para producción institucional está en la "Lista de salida a producción": servicio de sistema operativo administrado por IT, TLS, revisión de secretos por IT, cifrado en reposo, política de retención/backup aprobada, y el corpus/carga/auditoría PII final. El camino de Celery/Redis (workers distribuidos, para escalar más allá de una máquina) sigue siendo un modo de despliegue aparte, fuera del alcance de `anonimizacion` -- no publicar ni habilitar corridas institucionales hasta completar esa lista.

## Instalación base

1. Crear un entorno Python 3.11 o superior administrado por IT.
2. Instalar el paquete y las dependencias de operación desde el repositorio aprobado. Esto registra el comando `anonimizacion` (mismo entorno, editable):

   ```powershell
   python -m pip install -e .
   ```

3. Crear el archivo de variables protegido a partir de `deploy/variables-entorno.example` (el pepper y el secreto del panel). No versionar su copia real.
4. Copiar `deploy/anonimizacion.toml.example` como `anonimizacion.toml` junto a donde se va a correr el comando, y completar `db_url`, `raiz` y (si corresponde) `entrada`. Este archivo NUNCA lleva secretos -- ver el comentario del propio ejemplo.
5. Verificar que todo esté en orden antes de operar:

   ```powershell
   anonimizacion diagnosticar
   ```

   Corrige cada línea marcada `[FALTA]` (base apagada, migraciones desactualizadas, pepper/secreto sin configurar, carpeta sin permisos) antes de continuar -- cada mensaje dice qué hacer.
6. Ejecutar la validación de desarrollo antes de promover un cambio:

   ```powershell
   pytest -q
   ```

7. Registrar el servicio con la cuenta institucional definida abajo, con `ExecStart`/equivalente apuntando a `anonimizacion servir` (ver "Servicio administrado"). Para procesar una carpeta puntual (fuera del panel), el comando es `anonimizacion procesar --entrada <carpeta>`.

## Servicio administrado

La instalación debe ser un servicio administrado por IT: Windows Service en servidores Windows o systemd en Linux. Docker puede ser un detalle de infraestructura de IT, nunca un requisito para el médico u operador.

El servicio debe cargar variables protegidas del gestor institucional o de un archivo con ACL restringida. Debe ejecutarse con una cuenta dedicada; no con una cuenta personal ni con administrador/root.

> [!warning]
> `anonimizacion servir` (WSGI, `wsgiref` + hilos -- ver el docstring de `scripts/servir_panel.py`) es el comando real, pero el repositorio todavía NO empaqueta un instalador ni una unidad de servicio (`ExecStart`/nombre de servicio de Windows) lista para pegar: eso sigue siendo tarea de IT, fuera del alcance de este cambio (evaluado y descartado deliberadamente -- ver la justificación en `sdd/arranque-para-el-instituto/apply-progress`). Esta guía define los controles requeridos; IT decide el nombre de servicio y la unidad concreta de su plataforma.

## Variables protegidas

Usar `deploy/variables-entorno.example` sólo como catálogo. La cuenta de servicio necesita leer el archivo real, pero los usuarios interactivos y el navegador no.

| Variable | Uso actual | Regla institucional |
|---|---|---|
| `CELERY_BROKER_URL` | Broker Celery; por defecto local en desarrollo. | Usar endpoint Redis interno, con TLS/credenciales si IT lo requiere. |
| `CELERY_RESULT_BACKEND` | Backend de resultados Celery. | Mantenerlo en red interna y separado del dataset. |
| `CELERY_WORKER_CONCURRENCY` | Límite de workers entre 1 y 16. | Empezar con un valor bajo y medir CPU/RAM/DB antes de aumentarlo. |
| `CELERY_TASK_ALWAYS_EAGER` | Sólo desarrollo/pruebas sin Redis. | Debe ser `0` o estar ausente en un servicio real. |
| `ANONIMIZACION_PEPPER` / `ANONIMIZACION_PEPPER_ARCHIVO` | Pepper HMAC que hace irreversibles las claves de pseudonimización (`pseudonimizacion/almacen_pepper.py`); lo lee `anonimizacion diagnosticar`/`procesar`/`servir` al arrancar. | Guardar separado del dataset y rotarlo mediante procedimiento controlado. |
| `ANONIMIZACION_PANEL_SECRETO` / `ANONIMIZACION_PANEL_SECRETO_ARCHIVO` | Secreto HTTP Basic Auth del panel (`web/secreto_panel.py`); obligatorio con `--escuchar-red`. | Guardar en gestor de secretos; rotarlo no afecta datos ya escritos. |
| `ANONIMIZACION_DB_URL` | URL de Postgres sólo para correr Alembic a mano (`migrations/env.py`). | Guardar en gestor de secretos; nunca en repositorio, logs o manifiestos. |
| `db_url` (en `anonimizacion.toml`, NO es variable de entorno) | URL de Postgres que usan `anonimizacion procesar`/`servir` en operación normal -- ver `deploy/anonimizacion.toml.example`. | Riesgo conocido, heredado de `--db-url` en los scripts anteriores (no introducido por este cambio): la URL de SQLAlchemy incluye usuario y clave embebidos (`postgresql+psycopg://usuario:clave@host/db`). Usar un rol de aplicación de bajo privilegio, nunca superusuario, y restringir permisos del archivo -- separar la credencial de la URL queda pendiente de un cambio futuro. |

## Permisos y almacenamiento

| Recurso | Cuenta de servicio | Portal/operador | Regla |
|---|---|---|---|
| Carpeta de entrada | Lectura | Sólo selecciona una ruta autorizada | Nunca subir PDFs desde el navegador. |
| Originales | Lectura controlada | Sin acceso directo | Cifrados en reposo y separados del dataset. |
| Cuarentena | Escritura/lectura de revisión autorizada | Sin acceso directo | Cifrada, con metadata segura y retención independiente. |
| Dataset anonimizado | Escritura | Lectura según rol de investigación | No debe incluir PDFs, DNI, nombres, rutas ni secretos. |
| PostgreSQL/Redis | Acceso con credenciales del servicio | Sin acceso | Segmentación de red y mínimo privilegio. |
| Variables protegidas | Lectura | Sin acceso | ACL sólo para administradores de secretos y cuenta de servicio. |

Las raíces de entrada las configura IT. El inventariador resuelve rutas y omite enlaces que salen de una raíz autorizada, pero la ACL del sistema operativo es la defensa principal.

## Backups, retención y restauración

Antes de una corrida institucional, IT debe aprobar y registrar:

- **Backup:** frecuencia, cifrado, ubicación, responsable y prueba de restauración de PostgreSQL, configuración y dataset anonimizado.
- **Originales y cuarentena:** período de retención, responsable de borrado seguro, cifrado y proceso de acceso excepcional.
- **Dataset anonimizado:** versión, backup y criterios de conservación para reproducir resultados de investigación.
- **Prueba de restauración:** ejercicio periódico que restaure una base aislada y verifique que no se expone PII en logs/reportes.

No existe un período de retención decidido en el código; definirlo con el protocolo de investigación y la institución antes de operar.

## Rollback seguro

1. Deshabilitar la creación de nuevas corridas en el portal.
2. Dejar finalizar o detener workers de forma controlada; no borrar la base ni la cuarentena.
3. Conservar estados, auditoría y originales cifrados para poder investigar/reanudar.
4. Revertir la versión del servicio sólo después de verificar migraciones y compatibilidad de estados.
5. Volver a habilitar corridas únicamente tras una prueba controlada con datos sintéticos.

Postgres es la única salida del pipeline: no hay una segunda proyección (bundles/Parquet) que desactivar por separado -- ver `docs/pipeline.md` sobre por qué se eliminó (`chore/resolver-codigo-desconectado`).

## Lista de salida a producción

- [ ] Servicio real de corridas compuesto y probado contra PostgreSQL/Redis.
- [ ] Autenticación institucional, TLS y autorización por rol para el portal.
- [ ] Gestor de secretos y ACL revisados por IT.
- [ ] Cifrado en reposo de originales y cuarentena verificado.
- [ ] Política de retención y backup/restauración aprobada.
- [ ] Corpus sintético, carga representativa y auditoría PII final ejecutados.
- [ ] Riesgo de señal cruda del ECG y política de datos de profesionales resueltos con el equipo clínico.
