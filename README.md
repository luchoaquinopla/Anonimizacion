# Pipeline de anonimización clínica

Pipeline interno para extraer, verificar, pseudonimizar y preparar datos estructurados desde PDFs clínicos de ECG, laboratorio y ecocardiograma. El modelo de investigación consumidor no forma parte de este repositorio.

## Estado

El núcleo de extracción, reconciliación, corridas durables y contratos de operación está implementado y probado. **No está listo aún para uso institucional masivo**: falta la integración durable completa, el despliegue institucional aprobado, el corpus sintético/carga y la auditoría final de PII.

## Uso (operador)

Un único comando instalado, `anonimizacion`, reemplaza a los dos scripts sueltos que existían antes:

```powershell
python -m pip install -e .          # una vez, lo hace IT
anonimizacion diagnosticar          # ¿está todo listo para operar?
anonimizacion procesar --entrada D:\pdfs-instituto
anonimizacion servir
```

`anonimizacion diagnosticar` verifica el pepper, el secreto del panel (si hace falta), que Postgres esté encendido y con las migraciones al día, y que la carpeta a procesar exista y se pueda leer -- y dice en castellano llano qué falta y cómo resolverlo, no un traceback. Los valores no secretos (URL de base, carpeta, puerto) se configuran una sola vez en un archivo `anonimizacion.toml` (ver [`deploy/anonimizacion.toml.example`](deploy/anonimizacion.toml.example)) en vez de banderas sueltas. El pepper y el secreto del panel siguen viniendo siempre de variable de entorno o de un archivo aparte -- nunca de ese archivo de configuración.

## Desarrollo

```powershell
python -m pip install -e .[dev]
pytest -q
```

No agregar PDFs reales ni PII al repositorio. Para pruebas sin Redis se puede usar `CELERY_TASK_ALWAYS_EAGER=1`.

## Despliegue institucional

La guía de instalación, variables protegidas, permisos, backups, retención y rollback está en [`deploy/operacion-institucional.md`](deploy/operacion-institucional.md). El archivo [`deploy/variables-entorno.example`](deploy/variables-entorno.example) es sólo un catálogo y no contiene secretos.

El portal debe ser interno y seleccionar rutas ya existentes en el servidor; no debe aceptar PDFs ni secretos desde el navegador.
