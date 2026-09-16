# Tareas: corrección de orientación de la señal de ECG

- [x] 1. Derivar la dirección del tiempo de la posición de los pulsos de calibración
      (`_direccion_y_referencia_pulsos`), nunca de una constante fija.
- [x] 2. Reordenar columnas por distancia real a los pulsos (`_asignar_derivaciones`),
      recuperando la asignación correcta de columna/fila (incluye aVR).
- [x] 3. Generalizar `_muestrear` para orientar cada trazo según la dirección resuelta.
- [x] 4. Agregar validación fisiológica obligatoria (`_validar_fisiologia`): Einthoven,
      Goldberger, correlación V1-grilla-vs-tira. Cualquier violación descarta la señal.
- [x] 5. Subir `VERSION_EXTRACTOR` a 2 y propagarlo a `SenalEcg.version_extractor` en
      `construir_senal`.
- [x] 6. Actualizar docstrings/comentarios que describían la orientación vieja.
- [x] 7. Reescribir `tests/fixtures/pdf_sintetico.py` (ECG) con la orientación real y
      contenido fisiológicamente consistente (Einthoven/Goldberger desde I/II).
- [x] 8. Actualizar `tests/extraccion/test_senal_ecg.py` (corpus de bajo nivel) para
      cumplir las nuevas validaciones fisiológicas.
- [x] 9. Agregar tests de regresión en `tests/fixtures/test_pdf_sintetico_ecg.py`:
      aVR recuperada, T después de R en II, rechazo con columnas invertidas, rechazo con
      filas intercambiadas.
- [x] 10. Verificar contra el ECG real por el camino de producción (sólo lectura, sin
       imprimir PII) y confirmar los valores físicos esperados.
- [x] 11. Correr `pytest -q`, `pytest -q -m postgres` (secuencial) y `ruff check .`.
