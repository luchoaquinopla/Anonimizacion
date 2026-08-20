# Informe de verificación SDD

**Cambio:** `verificar-fidelidad-extraccion-pdf`  
**Modo:** TDD estricto  
**Persistencia:** hybrid  
**Rama verificada:** `feat/pdf-extraction-reconciliation` en `78c98c2`  
**Fecha:** 2026-08-19

## Completitud

| Métrica | Valor |
|---|---:|
| Tareas totales | 17 |
| Tareas completas declaradas | 17 |
| Tareas incompletas | 0 |

## Ejecución

**Pruebas:** `pytest -q` → **339 passed** en 11.13 s.  
**Cobertura:** `pytest --cov=anonimizacion --cov-report=term-missing -q` → **339 passed**, cobertura total **97%**. Los módulos de reconciliación modificados están entre 89% y 100%; no hay módulo modificado debajo de 80%.  
**Chequeo de diff:** `git diff --check main...HEAD` encontró espacios finales preexistentes en el informe de verificación anterior (tres líneas); no afecta el código, pero debe limpiarse antes del merge final.

## Matriz de cumplimiento de especificación

| Requisito | Escenario | Evidencia de prueba | Resultado |
|---|---|---|---|
| Reconciliación previa | Aprobado habilita PII | `tests/pipeline/test_ejecutor.py` | ✅ COMPLIANT |
| Reconciliación previa | Rechazado bloquea PII y salida | `tests/integracion/test_lote_aislamiento.py` | ✅ COMPLIANT |
| Igualdad/procedencia | Valor respaldado | pruebas ECG, laboratorio y eco en `tests/reconciliacion/` | ✅ COMPLIANT |
| Igualdad/procedencia | Ausente, ambiguo o discrepante | `test_ecg_mortara.py`, `test_laboratorio_general.py`, `test_eco_doppler.py` | ✅ COMPLIANT |
| Inventario independiente | ECG completo | `test_ecg_mortara.py` | ✅ COMPLIANT |
| Inventario independiente | Medida ECG omitida | `test_ecg_mortara.py` | ✅ COMPLIANT |
| Colecciones 1:1 | Fila de laboratorio omitida | `test_laboratorio_general.py` | ✅ COMPLIANT |
| Colecciones 1:1 | Eco duplicado u omitido | `test_eco_doppler.py` | ✅ COMPLIANT |
| Whitelist | Texto permitido / clínico sin destino | inventariadores por Strategy | ⚠️ PARTIAL: la cobertura de patrones reconocidos está probada; no hay prueba directa del contrato de whitelist para un texto desconocido. |
| Cuarentena segura | Cobertura incompleta no persiste contenido sensible | `tests/integracion/test_lote_aislamiento.py`, `tests/salida/test_cuarentena.py` | ✅ COMPLIANT |
| Asociación selector→etiqueta→valor | ECG cruzado | `test_rechaza_medidas_ecg_asignadas_a_etiquetas_cruzadas` | ✅ COMPLIANT |
| Asociación selector→etiqueta→valor | Eco, incluidas medidas | No existe prueba de medida Eco cruzada; `eco.medida` usa selector genérico y valida presencia, no un selector etiqueta-específico. | ❌ UNTESTED |

**Resumen:** 10/12 escenarios conformes, 1 parcial, 1 sin prueba ni cumplimiento demostrable.

## Coherencia de diseño

| Decisión | Estado | Evidencia |
|---|---|---|
| Reconciliar antes de PII | ✅ | `pipeline/ejecutor.py::_resolver_documento` invoca `reconciliar` antes de `clasificar_pii`. |
| Cobertura PDF→modelo independiente | ✅ | Strategies inventarían `TextoExtraido` y `inventario.py` compara claves y cardinalidad. |
| Cuarentena sin datos crudos | ✅ | `ErrorDocumento` y `EscritorCuarentena` solo trasladan documento, etapa, código, campo y página. |
| Migración de metadata segura | ✅ | `0002_metadata_segura_cuarentena.py` agrega solo `campo` y `pagina`. |
| Asociación selector→etiqueta→valor en ECG y Eco | ❌ | ECG ancla selectores específicos. Eco emite `ReferenciaCampo(..., selector="eco.medida")` para toda medida y `_asociacion_eco` para `eco.medida` busca solo el valor; no hay selector que identifique la etiqueta de la medida. |

## Cumplimiento TDD estricto

| Chequeo | Resultado | Detalle |
|---|---|---|
| Evidencia TDD reportada | ⚠️ | `apply-progress` contiene tabla, pero no usa los estados requeridos `✅ Written` / `✅ Passed` ni una lista verificable de archivos por tarea. |
| RED confirmado | ❌ | No es posible cruzar cada tarea con un archivo de prueba y un estado RED conforme al protocolo. |
| GREEN confirmado | ⚠️ | La suite actual pasa (339), pero la tabla no permite demostrarlo por cada tarea. |
| Triangulación | ⚠️ | Hay múltiples casos para ECG/firma, pero falta el caso cruzado de medida Eco. |
| Safety net | ⚠️ | La evidencia es narrativa y no permite verificar cada archivo modificado. |

**Cumplimiento TDD:** no verificable según el protocolo estricto; el artefacto de aplicación debe corregirse para expresar evidencia por tarea de forma auditable.

## Distribución de pruebas

| Capa | Resultado |
|---|---|
| Unitarias | Reconciliación, normalización, inventario, parsers y dominio. |
| Integración | Pipeline, aislamiento de lote y cuarentena. |
| E2E | No hay suite browser/HTTP; no es necesaria para este pipeline de procesamiento local. |

## Calidad de assertions

No se detectaron tautologías, assertions sin ejecutar código de producción ni loops fantasma en los tests revisados. Las assertions verifican códigos, campos, páginas y efectos de bloqueo.

## Hallazgos

### CRITICAL

1. **La asociación de medidas Eco no cumple selector→etiqueta→valor.** `parseo/eco_doppler.py` asigna a todas las medidas el selector genérico `eco.medida`; `_asociacion_eco` valida solo que el valor aparezca en la página. Falta una prueba de asignación cruzada de dos medidas Eco y un selector/evidencia que ancle cada nombre de medida a su valor. Por lo tanto, no está demostrado que un valor repetido o cruzado pertenezca a la etiqueta estructurada correcta.
2. **La evidencia TDD obligatoria no es verificable bajo modo estricto.** `apply-progress` no aporta los estados y archivos exigidos para RED/GREEN por tarea. La suite verde no sustituye esa trazabilidad de proceso.

### WARNING

1. Falta una prueba directa de whitelist para texto desconocido/no clínico frente a texto clínico reconocido sin destino.
2. `git diff --check main...HEAD` informa tres espacios finales en el informe anterior.

### SUGGESTION

1. Cuando se corrija la medida Eco, agregar también casos con dos columnas y mismo valor numérico para etiquetas distintas.

## Veredicto

**FAIL** — La suite completa pasa, pero la garantía crítica de asociación etiqueta→valor para medidas Eco y la evidencia exigida por TDD estricto no están demostradas. No abrir ni aceptar el PR final hacia `main` hasta resolver ambos puntos y repetir esta verificación.
