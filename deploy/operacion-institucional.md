# Operación institucional

## Estado de este material

Esta guía prepara la operación institucional **sin declarar una instalación lista para producción**. El repositorio tiene workers Celery, una aplicación WSGI interna y configuración por variables de entorno; todavía no tiene un *composition root* que conecte el portal, el servicio durable de corridas, PostgreSQL, Redis, los reconciliadores y el publicador de punta a punta. No publicar ni habilitar corridas institucionales hasta completar esa integración y la lista de salida.

## Instalación base

1. Crear un entorno Python 3.11 o superior administrado por IT.
2. Instalar el paquete y las dependencias de operación desde el repositorio aprobado:

   ```powershell
   python -m pip install -e .
   ```

3. Crear el archivo de variables protegido a partir de `deploy/variables-entorno.example`. No versionar su copia real.
4. Ejecutar la validación de desarrollo antes de promover un cambio:

   ```powershell
   pytest -q
   ```

5. Registrar el servicio con la cuenta institucional definida abajo. El comando de arranque definitivo queda pendiente del composition root; no sustituirlo por un script manual que contenga secretos.

## Servicio administrado

La instalación debe ser un servicio administrado por IT: Windows Service en servidores Windows o systemd en Linux. Docker puede ser un detalle de infraestructura de IT, nunca un requisito para el médico u operador.

El servicio debe cargar variables protegidas del gestor institucional o de un archivo con ACL restringida. Debe ejecutarse con una cuenta dedicada; no con una cuenta personal ni con administrador/root.

> [!warning]
> El repositorio no provee todavía un ejecutable de producción que componga todos los contratos del pipeline. Por eso esta guía define los controles requeridos, pero no inventa `ExecStart`, un nombre de servicio ni un comando de portal que hoy no existen.

## Variables protegidas

Usar `deploy/variables-entorno.example` sólo como catálogo. La cuenta de servicio necesita leer el archivo real, pero los usuarios interactivos y el navegador no.

| Variable | Uso actual | Regla institucional |
|---|---|---|
| `CELERY_BROKER_URL` | Broker Celery; por defecto local en desarrollo. | Usar endpoint Redis interno, con TLS/credenciales si IT lo requiere. |
| `CELERY_RESULT_BACKEND` | Backend de resultados Celery. | Mantenerlo en red interna y separado del dataset. |
| `CELERY_WORKER_CONCURRENCY` | Límite de workers entre 1 y 16. | Empezar con un valor bajo y medir CPU/RAM/DB antes de aumentarlo. |
| `CELERY_TASK_ALWAYS_EAGER` | Sólo desarrollo/pruebas sin Redis. | Debe ser `0` o estar ausente en un servicio real. |
| `DATABASE_URL` | Requerida por la composición PostgreSQL futura; no es leída aún por el módulo de workers. | Guardar en gestor de secretos; nunca en repositorio, logs o manifiestos. |
| `ANONIMIZACION_PEPPER` | Requerido por la composición HMAC futura; no es leído aún desde este archivo. | Guardar separado del dataset y rotarlo mediante procedimiento controlado. |

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
