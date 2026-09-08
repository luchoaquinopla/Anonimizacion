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

### Fixtures de calibración a partir de PDFs reales

Hoy no hay ningún fixture derivado de un documento real en `tests/`: la calibración de los parsers de ECG, laboratorio y eco vive sólo en prosa dentro de sus docstrings, así que un refactor puede descalibrarlos en silencio. `anonimizacion esqueleto` convierte un PDF real -- que quien lo tenga en su máquina nunca debe copiar al repositorio -- en un fixture de texto sin PII:

```powershell
anonimizacion esqueleto D:\ruta\a\un\ecg-real.pdf           --salida tests/fixtures/esqueletos/ecg-01.txt
anonimizacion esqueleto D:\ruta\a\un\laboratorio-real.pdf    --salida tests/fixtures/esqueletos/laboratorio-01.txt
anonimizacion esqueleto D:\ruta\a\un\ecocardiograma-real.pdf --salida tests/fixtures/esqueletos/eco-01.txt
```

El comando imprime en la terminal el tipo de documento detectado y el puntaje de la firma (cuántos marcadores de `deteccion/firmas/` matchearon), para ver con cuánta evidencia se reconoció cada muestra. El texto se enmascara por **allowlist estructural, no por detección de PII** (ver `src/anonimizacion/esqueleto.py`): todo se tapa por forma (letras → `X`, dígitos → `0`) salvo las etiquetas, marcadores de firma y unidades que el propio código ya conoce -- la propiedad "nunca sale un nombre real" vale por construcción, no por la calidad de un detector. Los archivos `.txt` resultantes sí son versionables y sí deben commitearse en `tests/fixtures/esqueletos/`.

**El PDF original nunca debe copiarse al repositorio** -- sólo el `.txt` que produce este comando.

## Instalación en una computadora del instituto (sin experiencia técnica)

Para instalar el panel en la computadora de un operador que no programa, ver [`docs/instalacion-para-el-instituto.md`](docs/instalacion-para-el-instituto.md): dos scripts de PowerShell (`scripts/instalar.ps1` y `scripts/iniciar_panel.ps1`) hacen el entorno virtual, la instalación de dependencias, el modelo de spaCy, los secretos y el arranque del panel, con salida en español y sin dejar nada a medias en silencio.

## Despliegue institucional

La guía de instalación, variables protegidas, permisos, backups, retención y rollback está en [`deploy/operacion-institucional.md`](deploy/operacion-institucional.md). El archivo [`deploy/variables-entorno.example`](deploy/variables-entorno.example) es sólo un catálogo y no contiene secretos.

El portal debe ser interno y seleccionar rutas ya existentes en el servidor; no debe aceptar PDFs ni secretos desde el navegador.
