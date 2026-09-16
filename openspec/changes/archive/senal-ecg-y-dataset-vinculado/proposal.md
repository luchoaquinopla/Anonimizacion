# Propuesta: señal de ECG y dataset vinculado

## Intención

Dejar el pipeline listo para los ~400.000 PDFs reales. Hoy el ECG sale sin señal (sólo encabezado + 5 medidas) y no hay salida que un investigador pueda llevar a Colab. El trazado del PDF es **vectorial** (medido), así que la señal se recupera sin OCR ni acceso al equipo.

## Alcance

### Dentro
- Extraer con `get_drawings()` 12 derivaciones (1238 muestras) + ritmo V1 (5000) a 500 Hz, en mV, calibrando con los pulsos. Nunca se lee texto.
- Validación geométrica: si el layout no coincide, el ECG se publica con `senal` en `campos_no_extraidos` (no va a cuarentena).
- Tabla `senal_ecg` (1:1 con `estudio`, binario comprimido), migración `0013`.
- Subcomando `exportar`: episodios vinculados (señal + laboratorio + eco + completitud) a Parquet + manifiesto.
- El generador sintético dibuja trazos conocidos (oráculo).
- Verificador de PII lineal del banco; cierre de 5.1/5.2 de `operacion-segura-y-escalable`.

### Fuera
- Adaptador en `modelo-hvi` (otro repo), renombrar "Mortara", agrupar escrituras (requiere la base en la nube), botón de exportar en el panel, tareas 4.3c/4.4/4.5.

## Enfoque

| Tema | Decisión | Por qué |
|---|---|---|
| Frecuencia | 500 Hz nativo, mV, + máscara | Sin pérdida y sin atarse a un modelo. `modelo_hvi` decima ×2 (señal ya filtrada a 40 Hz, sin aliasing): 1238/2 = 619 = `EsquemaPdf` |
| Dónde vive | Columna binaria en la base, no `.npz` sueltos | Misma transacción e idempotencia (`clave_documento`) que el estudio; un respaldo; un viaje por ECG; ~8 GB/100k aceptable |
| Salida | Exportación derivada de la base | La base sigue siendo la fuente de verdad; archivos reproducibles |

## Capacidades

### Nuevas
- `extraccion-senal-ecg`: trazos vectoriales → señal calibrada + máscara, sin texto.
- `exportacion-dataset-vinculado`: dataset por episodio; el manifiesto declara Hz, orden de derivaciones y ventanas.

### Modificadas
- `pdf-text-extraction`: el escenario "trazado rasterizado" es falso; pasa a vectorial.
- `document-parsing`: el ECG entrega señal opcional.
- `anonymized-output`: admite exportación a archivo derivada de PostgreSQL.
- `corpus-sintetico-clinico` (cambio abierto): ECG sintético con trazos.

## Áreas afectadas

| Área | Impacto |
|---|---|
| `extraccion/senal_ecg.py`, `salida/exportacion.py`, `migrations/versions/0013_*` | Nuevo |
| `dominio/modelos.py`, `pipeline/ejecutor.py`, `salida/{modelos_orm,destinos/postgres}.py`, `cli.py`, `pyproject.toml` | Modificado |
| `tests/fixtures/{pdf_sintetico,plantilla_documento,corpus_piloto}.py` | Modificado |

## Entregas encadenadas

1. Extracción + trazos sintéticos (~350 líneas).
2. Dominio + persistencia + completitud (~300).
3. Exportación (~350).
4. Verificador lineal + cierre de la fase 5 (~150).

## Riesgos

| Riesgo | Prob. | Mitigación |
|---|---|---|
| Layout medido sobre UN ECG | Alta | Validación estricta; marca incompleta, nunca señal dudosa |
| Deriva del contrato con `modelo_hvi` | Media | Manifiesto + test de contrato |
| Fabricante ("Mortara" vs GE 12SL) | Baja | Pregunta al instituto |

## Pendiente de terceros

- Instituto: fabricante/firmware, más ECGs de muestra.
- Creación de la base en la nube.
- `modelo-hvi`: adaptador que lea la exportación.

## Rollback

Cambio aditivo: revertir entregas en orden inverso; el downgrade de `0013` elimina `senal_ecg`; la exportación sólo lee.

## Criterios de éxito

- [ ] ECG sintético: señal recuperada con error ≤ 0,01 mV contra el oráculo.
- [ ] ECG real: 12 + 1 trazos, 500 Hz, ganancia 10 mm/mV.
- [ ] Auditoría PII de la exportación: 0 coincidencias.
- [ ] La exportación alimenta `armar_entrada` tras decimar ×2, sin otra transformación.
- [ ] El verificador de PII escala linealmente.
