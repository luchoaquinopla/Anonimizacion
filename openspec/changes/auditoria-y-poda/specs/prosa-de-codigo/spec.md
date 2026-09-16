# Especificación: poda de la prosa del código

Capacidad nueva (Entrega 6). De ~6.020 líneas de docstring+comentario sobre ~9.500 de
código ejecutable, migra el *por qué* narrativo a Obsidian y comprime los invariantes
medidos a una línea con puntero. Evidencia: `auditoria/consolidado-2026-09` (obs #1338),
`proposal.md` sección "Entrega 6".

## Requisito 1: orden obligatorio — migrar antes de podar

Ningún contenido narrativo **MUST** eliminarse del código sin que su equivalente exista
antes en Obsidian. La migración a Obsidian **MUST** completarse como criterio de
aceptación de la entrega, no como un paso suelto posterior.

#### Escenario: PR rechazado por podar sin migrar
- **Given** un diff que elimina un bloque de docstring narrativo
- **When** no existe una nota de Obsidian previa que documente ese contenido
- **Then** el PR de la Entrega 6 se rechaza

## Requisito 2: docstrings de máximo 2 líneas

Todo docstring en `src/anonimizacion/` **MUST** tener como máximo 2 líneas (qué hace la
función, qué devuelve), salvo excepción justificada explícitamente en el PR.

#### Escenario: docstring largo se recorta
- **Given** un docstring de producción de más de 2 líneas que narra decisiones o
  historia
- **When** se aplica la Entrega 6
- **Then** el docstring queda en 2 líneas o menos
- **And** el contenido narrativo removido existe en una nota de Obsidian

## Requisito 3: lista cerrada de invariantes protegidos

Los siguientes invariantes **MUST** sobrevivir la poda, comprimidos a una línea con
puntero a Obsidian (ej. `# 875 MB RSS por motor -- ver D-0XX en Obsidian`). Esta lista es
cerrada: ningún ítem **MUST** perderse, y ninguna adición nueva a la lista se acepta
fuera de esta especificación sin pasar por `sdd-propose`.

| Invariante | Evidencia | Por qué no se puede perder |
|---|---|---|
| 875 MB RSS por `MotorPii`, medido con `K32GetProcessMemoryInfo`/ctypes | `despacho_paralelo.py:79-80,217,339,752` | Fija el grado de concurrencia; perderlo lleva a agotar memoria sin aviso |
| Razonamiento del grado de concurrencia (2x núcleos lógicos; tope de reintentos por grupo revisado a `MAX_REINTENTOS_POR_GRUPO = 1`, es decir 2 cargas totales -- intento normal + 1 reintento aislado) | `despacho_paralelo.py:68-117,160,171,179` | Es la justificación del default de `--procesos`; sin ella el número parece arbitrario |
| Motivo de cada `noqa: C901` | `pyproject.toml:56-72` | Las funciones exentas no se tocan sin corpus de PDFs reales; ya se descalibraron dos veces |
| Cartel anti-espejo (esquema Arrow) | `tests/salida/test_esquema_arrow_de_exportacion.py:1-13` | Advierte contra reintroducir un test que compara el código con sí mismo |
| Cartel anti-espejo (codec de señal) | `tests/salida/test_codec_senal.py` | Misma clase de advertencia, distinto módulo |
| Latencias de red medidas contra Postgres (mediana 54,9 ms São Paulo; ~366 ms RDS sin `pre_ping`) y el timeout de 5 s derivado | `salida/destinos/postgres.py:87-135` | El timeout y el uso de `pre_ping` dejan de tener justificación sin el dato medido |
| Constantes geométricas de calibración de la señal ECG (`_ANCHO_TRAZO_PT = 0.43`, correlación V1-grilla r=1,000, umbral de ruido ~4-5% del RMS) | `extraccion/trazos_pymupdf.py:22`, `extraccion/senal_ecg.py:10-85` | Son mediciones contra el ECG real; sin el puntero a su origen, un ajuste futuro no sabe qué margen tiene |
| Trade-off medido del piso de confianza del reconocedor de DNI | `pii/reconocedores/dni_ar.py:43` | Bajar el piso sin saber por qué se fijó ahí reintroduce falsos negativos ya descartados |

**Corrección (verificada contra el código en `sdd-apply`, PR6f)**: la fila del umbral de
grupo tóxico decía "revisado de 3 a 4". Es falso -- `MAX_REINTENTOS_POR_GRUPO = 1` (2 cargas
en total). El "4" real en el código es `procesos=4`, la cantidad de procesos del experimento
que reprodujo el defecto del culpable equivocado, no una revisión del tope de reintentos.

#### Escenario: invariante presente después de la poda
- **Given** cualquier invariante de la tabla anterior
- **When** se completa la Entrega 6
- **Then** existe una línea en el código que lo referencia
- **And** existe una nota de Obsidian con el detalle completo

#### Escenario: PR rechazado por perder un invariante de la lista
- **Given** un diff de la Entrega 6
- **When** alguno de los invariantes de la tabla no tiene línea ni puntero en el código
  resultante
- **Then** el PR se rechaza

## Requisito 4: corrección de prosa desincronizada

`cli.py:20-34` **MUST** dejar de citar el PR #40 como abierto (está mergeado en
`847e711`). `docs/pipeline.md:194` **MUST** dejar de citar
`extraction/pymupdf_text.py` (inexistente) y referenciar el módulo real
`extraccion/texto_pymupdf.py`.

#### Escenario: `cli.py` sin referencia caduca
- **Given** `cli.py:20-34` después de la Entrega 6
- **When** se busca la cadena "PR #40 abierto"
- **Then** no hay coincidencias

#### Escenario: `docs/pipeline.md` referencia el módulo real
- **Given** `docs/pipeline.md` después de la Entrega 6
- **When** se busca `extraction/pymupdf_text.py`
- **Then** no hay coincidencias
- **And** el documento referencia `extraccion/texto_pymupdf.py`

## Requisito 5: el volumen de prosa es informativo, no compuerta

El conteo total de líneas de prosa **MUST NOT** usarse como criterio de aceptación de la
entrega. El criterio de aceptación **MUST** ser el Requisito 3 (lista cerrada intacta),
independientemente del número final de líneas.

#### Escenario: entrega aceptada con más líneas de las esperadas
- **Given** una poda que termina en ~1.800 líneas de prosa (por encima del objetivo
  informativo de ~1.500)
- **When** todos los invariantes de la lista cerrada están presentes y migrados
- **Then** la entrega se acepta

#### Escenario: entrega rechazada por menos líneas a costa de un invariante
- **Given** una poda que termina en ~1.400 líneas de prosa
- **When** un cartel anti-espejo de la lista cerrada quedó eliminado sin migrar
- **Then** la entrega se rechaza, sin importar el número de líneas alcanzado
