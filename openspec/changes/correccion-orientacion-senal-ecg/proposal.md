# Propuesta: corregir la orientación del tiempo en la señal de ECG

## Problema

`extraccion/senal_ecg.py` (openspec `senal-ecg-y-dataset-vinculado`) asumía que el tiempo
avanza con Y creciente, sin verificarlo contra la geometría real. Contra el ECG real (camino
de producción, `pipeline/ejecutor.py`), el tiempo corre con Y DECRECIENTE. Esa suposición
incorrecta producía tres fallas simultáneas, todas silenciosas (la señal se aceptaba como
válida):

1. **Cada derivación queda invertida en el tiempo** (la onda T aparece antes del QRS).
2. **Columnas cruzadas**: lo que el extractor llamaba I/II/III era en realidad V4/V5/V6;
   aVR/aVL/aVF era V1/V2/V3; V1/V2/V3 era aVR/aVL/aVF; V4/V5/V6 era I/II/III.
3. **aVR real se pierde**: el extractor descartaba (sobrescribía con la tira) el trazo que
   creía "V1 de la columna", que en realidad era aVR.

## Evidencia

Contra el ECG real (`D:\ejemplos_pdf\document (34).pdf`, sólo lectura, nunca commiteado):
los pulsos de calibración quedan en el extremo de Y ALTA (762,5–779,2 pt), más allá de
TODA derivación (máximo medido 761,4 pt) — el tiempo avanza alejándose de ellos, hacia Y
decreciente. Las etiquetas de derivación del propio PDF confirman la disposición real:
I/II/III junto a la columna de mayor Y (586–761), aVR/aVL/aVF junto a 409–584, V1/V2/V3
junto a 232–407, V4/V5/V6 junto a la columna de menor Y (55–230) — exactamente cruzado
respecto de lo que el extractor viejo asumía.

Tras el fix: Einthoven (RMS de `II − (I+III)` sobre RMS de `II`) da 5,15%; Goldberger (RMS
de `aVR+aVL+aVF` sobre RMS combinado) da 6,28%; ambos muy por debajo del margen (20%). En
lead II, la onda P cae a −184 ms del R y la T a +250 ms — consistente con un ECG real (PR
del equipo: 186 ms). Antes del fix, la señal se aceptaba en silencio con las derivaciones
cruzadas y sin verificación fisiológica alguna.

## Alcance

- Derivar la dirección del tiempo de la posición de los pulsos de calibración (nunca de
  una constante), y usarla para ordenar columnas, orientar cada trazo y orientar la tira.
- Recuperar aVR (ya no se pierde una vez corregido el orden de columnas).
- Agregar una validación fisiológica obligatoria (Einthoven, Goldberger, V1-grilla-vs-tira)
  antes de aceptar la señal — cualquier violación descarta la señal completa (`None`).
- Subir `SenalEcg.version_extractor` a 2 en toda señal producida por el extractor corregido
  (`version_extractor == 1` queda documentado como inválido, sin migración de datos: no hay
  base de producción poblada).
- Reescribir el fixture sintético (`tests/fixtures/pdf_sintetico.py`) con la orientación
  real y contenido fisiológicamente consistente (Einthoven/Goldberger derivados de I/II, no
  derivaciones independientes).

## Fuera de alcance

- Cambios al esquema de storage (`version_extractor` ya existía como columna).
- Migración de datos: no hay filas de producción con `version_extractor = 1`.
- El diseño original (`openspec/changes/archive/senal-ecg-y-dataset-vinculado/design.md`)
  fijaba el eje del tiempo (vertical, correcto) pero no su SENTIDO — este cambio corrige
  únicamente el sentido, no reabre esa decisión.
