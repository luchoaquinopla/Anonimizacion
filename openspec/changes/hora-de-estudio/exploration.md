# Exploración: hora del estudio

## Por qué existe este cambio

El delta temporal entre el electrocardiograma y el laboratorio más cercano es una **variable
de investigación central** del proyecto, no un metadato administrativo. El codirector médico
lo planteó explícitamente: cuanto más cerca esté el laboratorio del ECG, más válida es la
correlación, y el caso más valioso es el mismo día con hora conocida. Esto pesa especialmente
en el potasio, cuya concentración varía en el orden de horas.

Hoy el pipeline **no puede producir ese delta**, y no por falta de datos en el origen.

## Estado actual, verificado en código

### El ECG extrae la hora y la descarta

`parseo/ecg_mortara.py:93` captura fecha **y hora al segundo** en el header:

```python
"fecha": r"(\d{2}-[A-Za-z]{3}-\d{4}\s+\d{2}:\d{2}:\d{2})",
```

Y `parseo/ecg_mortara.py:234` la tira en la línea siguiente:

```python
def _parsear_fecha(texto: str) -> date:
    solo_fecha = texto.strip().split(" ")[0]
    return datetime.strptime(solo_fecha, "%d-%b-%Y").date()
```

### La normalización también trunca

`reconciliacion/normalizacion.py:30-38` — `normalizar_fecha_iso` llama `.date()` sobre
cualquier `datetime` parseado, aceptando sólo los formatos `%Y-%m-%d` y `%d/%m/%Y`.

### El dominio no tiene dónde guardarla

`dominio/modelos.py:46` y `:77` — `fecha_estudio: date` tanto en `DocumentoParseado` como en
`RegistroAnonimizado`. Ningún dataclass de `salida/modelos_salida.py` tiene campo de hora.

## Qué trae cada estudio, verificado contra muestras reales del instituto

Las muestras son PDFs clínicos reales y **no se incorporan al repositorio**. Sólo se registra
acá la estructura del layout.

| Estudio | Campo de fecha en el documento | Hora disponible | Precisión |
|---|---|---|---|
| ECG (Mortara) | Header, junto al identificador de estudio | **Sí** | segundo |
| Laboratorio | Campo `Fecha:` en el encabezado | **Sí**, en un campo propio rotulado `Hora de Extracción:` | minuto |
| Ecocardiograma | Campo `Fecha Estudio:` | **No** | día |

El hallazgo determinante es el laboratorio: la hora no está junto a la fecha, sino en un
campo separado con su propio rótulo, y **su semántica es la correcta** — es el momento de la
toma de la muestra, no el de impresión del informe. Para el potasio, ése es exactamente el
instante que importa.

El parser de laboratorio no la busca hoy: `parseo/laboratorio_general.py` sólo tiene patrones
`\d{1,2}/\d{1,2}/\d{4}`, sin componente horario. Lo mismo `parseo/eco_doppler.py`, pero ahí
es correcto porque el documento genuinamente no la trae.

## Decisión de modelado: la ausencia debe ser explícita

Un `date` → `datetime` a secas **sería un error**. El ecocardiograma no tiene hora; migrar el
tipo le asignaría las 00:00, y esa precisión inventada resulta indistinguible de una hora
real en cualquier análisis posterior. Contaminaría justamente la variable que motiva el
cambio.

El modelado correcto es `fecha_estudio: date` más un campo separado de hora **opcional**,
donde la ausencia significa "este documento no la trae" y no "medianoche".

Consecuencia derivada: el delta ECG↔laboratorio se puede calcular con precisión de minutos,
mientras que cualquier delta que involucre al ecocardiograma queda limitado al día. Eso es
aceptable y coherente con la realidad clínica — el ecocardiograma varía en semanas o meses,
no en horas — pero el consumidor del dato tiene que poder distinguir un caso del otro.

## Áreas afectadas

- `src/anonimizacion/dominio/modelos.py` — `DocumentoParseado`, `RegistroAnonimizado`
- `src/anonimizacion/parseo/ecg_mortara.py` — dejar de truncar
- `src/anonimizacion/parseo/laboratorio_general.py` — extraer el campo de hora de extracción
- `src/anonimizacion/parseo/eco_doppler.py` — sin hora, debe emitir ausencia explícita
- `src/anonimizacion/reconciliacion/normalizacion.py` — normalización de hora sin inferir
- `src/anonimizacion/reconciliacion/` — los reconciliadores por tipo deben poder citar la
  procedencia del nuevo campo, igual que hacen con los demás
- `src/anonimizacion/salida/modelos_salida.py`, `modelos_orm.py`, `constructor_registro.py`
- `migrations/versions/` — columna nueva
- `tests/calibracion/` — las tres compuertas uno a uno, que verifican campo por campo contra
  la muestra real
- `tests/carga/` — los oráculos son de igualdad estricta

## Riesgos

- **Precisión inventada**: cualquier default de hora (00:00 y similares) corrompe la variable
  de investigación. La ausencia debe viajar como ausencia hasta la salida.
- **Compuertas de calibración**: verifican contra muestras reales; agregar un campo obliga a
  actualizarlas, y son deliberadamente estrictas.
- **Zona horaria**: los documentos no declaran huso. Interpretar u ofrecer una conversión
  sería inferir un dato que no está. Debe registrarse como hora local del instituto, sin
  conversión, y documentarse esa decisión.
- **No confundir con la fecha de recepción**: el laboratorio tiene además una columna de
  resultados anteriores con sus propias fechas. El campo a extraer es el de extracción de la
  muestra del informe actual.
- Fuera de alcance: cinecoronariografía (sin muestra ni parser), el cálculo del delta en sí
  (es consumo aguas abajo, no responsabilidad de este pipeline) y cualquier normalización
  clínica de los valores.

## ¿Listo para propuesta?

Sí.
