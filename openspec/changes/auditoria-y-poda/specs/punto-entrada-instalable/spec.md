# Especificación: punto de entrada instalable

Capacidad nueva (Entrega 4). Cierra el defecto de despliegue: `anonimizacion procesar` y
`anonimizacion servir` funcionan desde checkout pero fallan instalados por wheel.
Evidencia: `cli.py:54,59`, `pyproject.toml:32,35` (auditoria/consolidado-2026-09, obs
#1338).

## Requisito 1: el CLI no depende de `scripts/` fuera del paquete

`anonimizacion.cli` **MUST** implementar la lógica de `procesar` y `servir` dentro de
`src/anonimizacion/`, sin cargar módulos de `scripts/` por ruta de archivo
(`spec_from_file_location`) ni re-parsear `sys.argv` con un segundo `argparse`.

#### Escenario: `scripts/procesar_carpeta.py` y `scripts/servir_panel.py` no se cargan
- **Given** el paquete instalado por wheel
- **When** se ejecuta `anonimizacion procesar` o `anonimizacion servir`
- **Then** la ejecución NO referencia ni carga archivos bajo `scripts/`

## Requisito 2: el comando funciona instalado por wheel

El sistema **MUST** tener un test que construya el wheel del paquete, lo instale en un
entorno virtual efímero (sin el checkout del repo en el path) y ejecute
`anonimizacion --help` y al menos un subcomando (`procesar` o `servir`) con éxito.

#### Escenario: `--help` funciona instalado por wheel
- **Given** el wheel construido e instalado en un venv efímero
- **When** se ejecuta `anonimizacion --help`
- **Then** el comando termina con código de salida 0

#### Escenario: un subcomando real funciona instalado por wheel
- **Given** el mismo venv efímero
- **When** se ejecuta el subcomando `procesar` (o `servir`) con argumentos válidos
- **Then** el comando se ejecuta sin el error de carga de `scripts/` que ocurre hoy
  instalado por wheel

#### Escenario: el test detecta una regresión al reintroducir el reenvío a `scripts/`
- **Given** el test de instalación por wheel en verde
- **When** se reintroduce a propósito una carga por ruta de archivo hacia `scripts/`
- **Then** el test falla

## Requisito 3: `_DB_URL_DEFAULT` en un solo lugar

El sistema **MUST** definir `_DB_URL_DEFAULT` en un único módulo. Los otros dos puntos
donde hoy está triplicado (`configuracion.py:52`, `procesar_carpeta.py:80`,
`servir_panel.py:107`) **MUST** importar ese valor único, no redeclararlo.

#### Escenario: un solo valor cambia el default en todos los usos
- **Given** el valor único de `_DB_URL_DEFAULT`
- **When** se cambia ese valor
- **Then** tanto `procesar` como `servir` usan el nuevo valor sin editar más de un lugar
