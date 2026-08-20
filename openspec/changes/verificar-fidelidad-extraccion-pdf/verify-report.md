# Verification Report — verificar-fidelidad-extraccion-pdf

**Modo de persistencia:** hybrid  
**Rama verificada:** `feat/pdf-extraction-reconciliation` (`404802a`)  
**Fecha:** 2026-08-19  
**Veredicto:** **FAIL**

## Evidencia de ejecución

| Comando | Resultado |
|---|---|
| `pytest tests/reconciliacion tests/pipeline tests/salida/test_cuarentena.py tests/integracion/test_lote_aislamiento.py -q` | ✅ 85 passed |
| `pytest -q` | ✅ 330 passed |
| `pytest -q --cov=anonimizacion --cov-report=term-missing` | ✅ 330 passed; 97% global |
| `git diff --check main...HEAD` | ✅ Sin errores |
| `ruff check ...` | ➖ No disponible en el entorno |

## Matriz de cumplimiento

| Requisito | Evidencia | Estado |
|---|---|---|
| Reconciliación antes de PII, pseudonimización y salida | `EjecutorPipeline._resolver_documento` invoca el reconciliador inmediatamente después de `parsear`; test E2E de omisiones confirma que no hay vínculos ni salidas | ✅ |
| Igualdad y procedencia semántica por campo | Hay validación de presencia/unicidad de valores y asociación estructurada para laboratorio, pero ECG y eco no consumen el selector para asociar etiqueta con valor | ❌ |
| Inventario independiente PDF→modelo | Strategies separadas para ECG, laboratorio y eco; tests de omisiones | ✅ |
| Cobertura 1:1 de colecciones | `verificar_cobertura` cruza `(id_campo, ordinal)`; laboratorio y eco verifican cardinalidad/ordinal | ✅ |
| Whitelist explícita | Whitelists/patrones de ECG y encabezados de laboratorio, con pruebas focalizadas | ✅ |
| Cuarentena segura y migración | `campo`/`pagina` permitidos, migración 0002 y prueba de columnas exactas | ✅ |

## Hallazgos

### CRITICAL

1. **El selector no participa en la comprobación de igualdad de ECG ni eco.**
   `ReferenciaCampo.selector` solo se valida al construirse en `reconciliacion/base.py`; no se consulta durante `reconciliar_referencias` en `reconciliacion/_comun.py`. Esa función cuenta el valor normalizado en toda la página, sin comprobar la relación selector/etiqueta→valor.
   Consecuencia: si el parser asigna a `PR interval` un valor que aparece una sola vez pero pertenece a `QRS duration` (o análogo en eco), la reconciliación puede aprobarlo. Esto incumple el requisito de que no se modifique la asociación campo–valor y la decisión de diseño de validar asociación selector-etiqueta-valor.
   No hay prueba de regresión que simule esta asociación cruzada para ECG o eco.

### WARNING

1. **La evidencia TDD de apply-progress no sigue el formato estricto solicitado.** Contiene una tabla y los archivos/pruebas existen y pasan, pero sus columnas RED/GREEN no expresan los estados explícitos `✅ Written` / `✅ Passed`. La auditoría puede corroborar 8 archivos de reconciliación y 53 pruebas unitarias focalizadas, pero no verificar formalmente cada ciclo RED desde el artefacto.

### SUGGESTION

1. Agregar `ruff` al entorno de desarrollo/CI para que el lint sea reproducible. La cobertura de archivos modificados es alta (reconciliación 89–100%, parsers 91–96%, ejecutor 97%), pero no reemplaza esa comprobación.

## TDD Compliance

| Check | Result | Details |
|---|---|---|
| TDD Evidence reported | ✅ | Existe en apply-progress |
| All tasks have tests | ✅ | Pruebas focalizadas para contratos, ECG, laboratorio, eco, pipeline y cuarentena |
| RED confirmed | ⚠️ | Archivos existen; formato de evidencia RED no es estricto |
| GREEN confirmed | ✅ | 85 focalizadas y 330 completas pasan |
| Triangulation adequate | ✅ | Igualdad, omisión, duplicación, cardinalidad y bloqueo E2E |
| Safety Net | ⚠️ | Evidencia narrativa, no tabla por archivo |

**Assertion quality:** ✅ No se detectaron tautologías, aserciones vacías ni bucles fantasma en los tests de reconciliación.

## Distribución de pruebas

| Layer | Tests | Files |
|---|---:|---:|
| Unit | 53 | 8 |
| Integration | 2 escenarios E2E | 1 |
| Pipeline/persistencia | 30 focalizadas | 4 |

## Cobertura de archivos modificados

- Reconciliación: 89–100% por archivo; `base.py` 89%, laboratorio 93%.
- Parsers modificados: ECG 91%, laboratorio 92%, eco 96%.
- Pipeline: `ejecutor.py` 97%, `etapas.py` 100%.
- Cuarentena/ORM: 100%.

## Conclusión

La cobertura bidireccional y el bloqueo temprano están implementados y probados, pero el objetivo central de fidelidad no se cumple completamente mientras la asociación selector→campo→valor no se verifique en ECG y eco. Corregir este hallazgo crítico y añadir regresiones antes de archivar o abrir el PR final hacia `main`.
