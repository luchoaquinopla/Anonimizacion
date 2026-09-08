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

La calibración de los parsers de ECG, laboratorio y eco vive en buena parte en prosa dentro de sus docstrings, así que un refactor puede descalibrarlos en silencio. `anonimizacion esqueleto` convierte un PDF real -- que quien lo tenga en su máquina nunca debe copiar al repositorio -- en un fixture de texto versionable, en dos modos posibles con propósitos DISTINTOS y complementarios (`--modo`, default `enmascarado`):

```powershell
# Modo enmascarado (default): valida DETECCIÓN DE TIPO y ESTABILIDAD DE LAYOUT.
anonimizacion esqueleto D:\ruta\a\un\ecg-real.pdf           --salida tests/fixtures/esqueletos/ecg-01.txt
anonimizacion esqueleto D:\ruta\a\un\laboratorio-real.pdf    --salida tests/fixtures/esqueletos/laboratorio-01.txt
anonimizacion esqueleto D:\ruta\a\un\ecocardiograma-real.pdf --salida tests/fixtures/esqueletos/eco-01.txt

# Modo parseable: valida PARSEO de punta a punta (--modo parseable).
anonimizacion esqueleto D:\ruta\a\un\ecg-real.pdf           --modo parseable --salida tests/fixtures/parseables/ecg-01.txt
anonimizacion esqueleto D:\ruta\a\un\laboratorio-real.pdf    --modo parseable --salida tests/fixtures/parseables/laboratorio-01.txt
anonimizacion esqueleto D:\ruta\a\un\ecocardiograma-real.pdf --modo parseable --salida tests/fixtures/parseables/eco-01.txt
```

Los dos modos comparten el 100% del resto del comando (extraer el PDF, resolver `--salida`, reportar errores sin ruta cruda) y la MISMA allowlist estructural -- por eso es una opción del subcomando existente y no un subcomando nuevo: lo único que cambia es la función de sustitución de lo que no es estructura.

**Diferencia entre los dos tipos de fixture -- ninguno lleva datos reales, cada uno prueba algo distinto:**

- **`tests/fixtures/esqueletos/` (modo enmascarado, default).** Todo token de contenido se tapa por FORMA: cada corrida de letras se vuelve una `X` por letra, cada corrida de dígitos un `0` por dígito, salvo las etiquetas, marcadores de firma y unidades que el propio código ya conoce (`ALLOWLIST_ESTRUCTURAL`, ver `src/anonimizacion/esqueleto.py`) -- la propiedad "nunca sale un valor real" vale por CONSTRUCCIÓN, no por la calidad de un detector. Sirve para probar **detección de tipo y estabilidad de layout** (`tests/deteccion/test_centinela_esqueletos.py`): al tapar los valores, NO puede afirmar que los parsers extraigan bien los datos.
- **`tests/fixtures/parseables/` (`--modo parseable`).** Mismo layout real y la misma allowlist, pero cada token de contenido se reemplaza por un sustituto SINTÉTICO plausible de la misma forma: otro número de la misma cantidad de dígitos, otra "palabra" de la misma longitud (pronunciable, preservando mayús/minús carácter a carácter), y fechas/horas VÁLIDAS y clínicamente coherentes entre sí (fecha de nacimiento anterior a la fecha de estudio, edad consistente con ambas). La sustitución es determinística (mismo valor de entrada → mismo sustituto siempre, en todo el documento) -- necesario porque el parser de laboratorio exige que el Nº de Petición no cambie entre páginas. Sirve para probar **parseo de punta a punta** (`tests/parseo/test_regresion_fixtures_parseables.py`): cuántos resultados/medidas/secciones se extraen, qué campos de header quedan poblados, valores puntuales con su unidad -- todo medido contra la corrida real y hardcodeado en el test (nunca leído del propio fixture, para que un parser roto no pueda "grabar" su propio resultado roto como el nuevo esperado).

El comando imprime en la terminal el tipo de documento detectado (y, sólo en modo enmascarado, el puntaje de la firma: cuántos marcadores de `deteccion/firmas/` matchearon). Los archivos `.txt` resultantes de AMBOS modos son versionables y deben commitearse.

**El PDF original nunca debe copiarse al repositorio** -- sólo el `.txt` que produce este comando, en cualquiera de los dos modos.

## Instalación en una computadora del instituto (sin experiencia técnica)

Para instalar el panel en la computadora de un operador que no programa, ver [`docs/instalacion-para-el-instituto.md`](docs/instalacion-para-el-instituto.md): dos scripts de PowerShell (`scripts/instalar.ps1` y `scripts/iniciar_panel.ps1`) hacen el entorno virtual, la instalación de dependencias, el modelo de spaCy, los secretos y el arranque del panel, con salida en español y sin dejar nada a medias en silencio.

## Despliegue institucional

La guía de instalación, variables protegidas, permisos, backups, retención y rollback está en [`deploy/operacion-institucional.md`](deploy/operacion-institucional.md). El archivo [`deploy/variables-entorno.example`](deploy/variables-entorno.example) es sólo un catálogo y no contiene secretos.

El portal debe ser interno y seleccionar rutas ya existentes en el servidor; no debe aceptar PDFs ni secretos desde el navegador.
