# Especificación: caracterización del comportamiento actual

Capacidad nueva (Entrega 0). Fija por escrito, con tests, lo que el sistema hace HOY —
antes de que las Entregas 1-6 lo toquen— para que cualquier cambio que lo altere sin
querer falle de inmediato. Evidencia: `auditoria/consolidado-2026-09` (obs #1338),
`proposal.md` sección "Entrega 0".

## Requisito 1: caracterización punta a punta del pipeline

El sistema **MUST** tener un test de caracterización que, sobre un corpus sintético
propio, ejecute las 9 etapas del pipeline para los 3 tipos de documento y fije las filas
resultantes en PostgreSQL y el registro de salida, cubriendo al menos: un episodio
completo, uno incompleto, uno ambiguo y uno en cuarentena.

Ninguna fixture de este test **MUST NOT** escribir sobre la base de desarrollo
compartida del puerto 5433: cada test crea y destruye la suya.

#### Escenario: episodio completo fija filas conocidas
- **Given** un corpus sintético con ECG, laboratorio y eco del mismo episodio
- **When** se ejecuta el pipeline punta a punta
- **Then** las filas de `episodio` y `estudio` en PostgreSQL coinciden con el fixture
  esperado

#### Escenario: el test detecta una regresión real
- **Given** el test punta a punta en verde
- **When** se rompe a propósito una etapa intermedia (ej. se fuerza que la reconciliación
  apruebe un campo sin evidencia)
- **Then** el test falla, y la evidencia de ese fallo queda registrada en el PR de la
  Entrega 0

## Requisito 2: contrato del CLI

El sistema **MUST** tener un test que, para cada subcomando de `anonimizacion`, fije el
conjunto de banderas aceptadas, sus valores por defecto efectivos y el código de salida
para al menos un caso de éxito y uno de error.

#### Escenario: banderas y defaults de `procesar`
- **Given** el CLI actual, ejecutado sin ninguna bandera opcional
- **When** se inspeccionan los valores efectivos que recibe la lógica de negocio
- **Then** coinciden con los defaults fijados por el test

#### Escenario: el test detecta un cambio de código de salida
- **Given** el test de contrato en verde
- **When** se rompe a propósito el manejo de un error del subcommand (se cambia el
  código de salida devuelto)
- **Then** el test falla

## Requisito 3: códigos de cuarentena observables

El sistema **MUST** tener un test que, para un conjunto conocido de entradas inválidas,
fije qué `CodigoErrorDocumento` produce cada una y en qué etapa (`ErrorDocumento.etapa`).

#### Escenario: entrada sin evidencia produce el código esperado
- **Given** un documento sintético cuyo campo requerido no tiene evidencia en el PDF
- **When** se procesa
- **Then** el `CodigoErrorDocumento` y la etapa registrados coinciden con el fixture

#### Escenario: el test detecta una etapa que cambió sin querer
- **Given** el test en verde
- **When** se rompe a propósito la etapa que se asigna a ese código
- **Then** el test falla

## Requisito 4: vista del embudo

El sistema **MUST** tener un test que, dado un conjunto conocido de documentos con
desenlaces variados, fije el desglose exacto que devuelve la vista del embudo
(`web/embudo_corrida.py`).

#### Escenario: desglose conocido
- **Given** un conjunto fijo de documentos con desenlaces publicado/apartado/desconocido
- **When** se calcula el embudo de la corrida
- **Then** el desglose por etapa coincide con el fixture

#### Escenario: el test detecta un desglose alterado
- **Given** el test en verde
- **When** se rompe a propósito el cálculo de una etapa del embudo
- **Then** el test falla

## Requisito 5: salida del reporte de corrida

El sistema **MUST** tener un test que fije la salida del reporte de corrida que hoy lee
`MetricasDespacho` (`despacho_paralelo.py:330`), para un conjunto conocido de resultados
de despacho.

#### Escenario: reporte con resultados mixtos
- **Given** una `MetricasDespacho` con éxitos, fallos y reintentos conocidos
- **When** se genera el reporte de corrida
- **Then** el contenido coincide con el fixture

#### Escenario: el test detecta una lectura incorrecta de métricas
- **Given** el test en verde
- **When** se rompe a propósito la lectura de `MetricasDespacho` en el reporte
- **Then** el test falla

## Requisito 6: regla de honestidad — todo test de caracterización debe poder fallar

Cada test escrito bajo los Requisitos 1-5 **MUST** validarse rompiendo a propósito el
comportamiento que dice proteger, y la evidencia de ese fallo (rojo) **MUST** quedar
registrada en el PR de la Entrega 0.

Un test de caracterización que pasa con el sistema roto **MUST NOT** aceptarse: es peor
que no tenerlo.

#### Escenario: test aceptado sin evidencia de rojo se rechaza
- **Given** un test de caracterización nuevo sin evidencia registrada de haber fallado
  alguna vez
- **When** se revisa el PR de la Entrega 0
- **Then** el test se rechaza hasta que se demuestre que puede fallar
