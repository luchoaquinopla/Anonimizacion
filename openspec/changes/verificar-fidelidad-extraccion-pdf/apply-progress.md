# Progreso de aplicación: verificar fidelidad de extracción desde PDF

**Modo:** TDD estricto
**Persistencia:** hybrid
**Rama verificada:** `feat/pdf-extraction-reconciliation` (`e299c00`)
**Estado:** 21/21 tareas implementadas; trazabilidad histórica reconstruida el 2026-08-19.

## Criterio de reconstrucción

Los PR 1–10 fueron commits atómicos que incorporaron pruebas y producción juntos. Git permite comprobar qué pruebas y qué implementación cambiaron, pero no conserva el orden temporal interno RED→GREEN de esos commits. Por eso, para las tareas 1.1–4.3, `RED` significa **evidencia reconstruida**, no una afirmación de que se conservó la ejecución histórica: se verificó el diff del commit indicado y se ejecutó ahora la prueba de aceptación contra la implementación final. Las tareas 5.1–5.5 conservan además la evidencia contemporánea original.

Esta distinción es deliberada: no se inventan salidas de pytest ni se presenta una prueba actual verde como si demostrara un RED histórico.

## Comandos de comprobación ejecutados durante la reconstrucción

| ID | Comando | Resultado verificable |
|---|---|---|
| C1 | `pytest -q tests/reconciliacion/test_normalizacion.py tests/dominio/test_modelos.py tests/dominio/test_errores.py tests/pipeline/test_ejecutor.py` | ✅ 49 passed |
| C2 | `pytest -q tests/reconciliacion/test_ecg_mortara.py tests/reconciliacion/test_laboratorio_general.py tests/reconciliacion/test_eco_doppler.py tests/reconciliacion/test_procedencia_parseadores.py tests/reconciliacion/test_registro.py` | ✅ 51 passed |
| C3 | `pytest -q tests/reconciliacion/test_inventario.py tests/reconciliacion/test_ecg_mortara.py` | ✅ 17 passed |
| C4 | `pytest -q tests/reconciliacion/test_laboratorio_general.py tests/reconciliacion/test_eco_doppler.py` | ✅ 39 passed |
| C5 | `pytest -q tests/pipeline/test_ejecutor.py tests/pipeline/test_etapas.py tests/integracion/test_lote_aislamiento.py tests/salida/test_cuarentena.py` | ✅ 17 passed |
| C6 | `pytest -q` | ✅ 344 passed |

## Evidencia del ciclo TDD

| Tarea | Archivos de prueba / producción | Safety net y GREEN | RED | Triangulación | REFACTOR |
|---|---|---|---|---|---|
| 1.1 | `tests/reconciliacion/test_normalizacion.py` / `reconciliacion/normalizacion.py` | C1 ✅ | ⚠️ Reconstruida desde `2177bb0`: igualdad de texto, número, fecha y rechazos añadidos con el normalizador; no hay ejecución RED histórica. | Espacios/mayúsculas, coma/punto y cambios semánticos prohibidos. | Normalizadores separados por tipo. |
| 1.2 | `tests/reconciliacion/test_normalizacion.py` / `reconciliacion/{base,normalizacion}.py` | C1 ✅ | ⚠️ Reconstruida desde `2177bb0`: pruebas de referencias seguras y módulos nuevos en el mismo diff; no hay ejecución RED histórica. | Referencia válida, selector con texto y selector fuera de whitelist. | Contrato común `ReferenciaCampo` y `ReconciliadorDocumento`. |
| 1.3 | `tests/dominio/test_modelos.py`, `tests/dominio/test_errores.py` / `dominio/{modelos,errores,referencias}.py` | C1 ✅ | ⚠️ Reconstruida desde `2177bb0`: pruebas de fuentes y códigos seguros añadidas con los modelos/errores. | Metadata permitida, inmutabilidad y rechazos de campo no declarado. | Códigos de reconciliación centralizados. |
| 1.4 | `tests/reconciliacion/test_normalizacion.py`, `tests/dominio/test_errores.py` / `dominio/referencias.py`, `dominio/errores.py` | C1 ✅ | ⚠️ Reconstruida desde `2177bb0`: pruebas de selectores y metadata sensible añadidas con el filtro. | Texto transportable, identificador no declarado y campo seguro. | Whitelist cerrada sin valores clínicos ni PII. |
| 2.1 | `tests/reconciliacion/test_ecg_mortara.py` / `reconciliacion/{_comun,ecg_mortara}.py`, `parseo/ecg_mortara.py` | C2 ✅ | ⚠️ Reconstruida desde `a7654da`: estrategia y pruebas ECG se incorporaron en el mismo diff. | Aprobación, ausencia/discrepancia, ambigüedad y fecha de nacimiento. | Algoritmo compartido en `_comun.py`. |
| 2.2 | `tests/reconciliacion/test_laboratorio_general.py` / `reconciliacion/laboratorio_general.py`, `parseo/laboratorio_general.py` | C2 y C4 ✅ | ⚠️ Reconstruida desde `a7654da`: pruebas y estrategia de laboratorio se incorporaron juntas. | Repetición por ordinal, discrepancia y texto ordenado. | Referencias por sección/ordinal. |
| 2.3 | `tests/reconciliacion/test_eco_doppler.py` / `reconciliacion/eco_doppler.py`, `parseo/eco_doppler.py` | C2 y C4 ✅ | ⚠️ Reconstruida desde `a7654da`: pruebas y estrategia Eco se incorporaron juntas. | Medida, texto, firma presente y formato legado. | Estrategia por página y firma opcional. |
| 2.4 | `tests/reconciliacion/test_registro.py`, `tests/reconciliacion/test_procedencia_parseadores.py` / `reconciliacion/registro.py`, `parseo/registro.py` | C2 ✅ | ⚠️ Reconstruida desde `a7654da`: registro y pruebas de Strategy/procedencia entraron juntos. | Tres tipos conocidos, tipo sin Strategy y página real del dato. | Registro único de Strategies y rechazo temprano. |
| 3.1 | `tests/reconciliacion/test_inventario.py` / `reconciliacion/{base,inventario,_comun}.py`, `dominio/errores.py` | C3 ✅ | ⚠️ Reconstruida desde `09727c4`: `HallazgoCobertura`, pruebas de claves y errores se incorporaron juntos. | Identificador no declarado, clave duplicada y destino sin hallazgo. | Cruce modelo↔inventario centralizado. |
| 3.2 | `tests/reconciliacion/test_inventario.py`, `tests/reconciliacion/test_ecg_mortara.py` / `reconciliacion/ecg_mortara.py` | C3 ✅ | ⚠️ Reconstruida desde `09727c4`: inventario ECG y prueba de medida omitida aparecen en el mismo diff. | Medida omitida, etiqueta repetida y cobertura completa del parser. | Inventario ECG separado del parseador. |
| 3.3 | `tests/reconciliacion/test_laboratorio_general.py` / `reconciliacion/laboratorio_general.py`, `parseo/laboratorio_general.py` | C4 ✅ | ⚠️ Reconstruida desde `6c35f6a`: cobertura de filas y ajustes de estrategia se incorporaron juntos. | Fila omitida, unidad/sección/ordinal incorrectos y resultado cualitativo. | Clave sección/subsección/ordinal. |
| 3.4 | `tests/reconciliacion/test_eco_doppler.py` / `reconciliacion/{eco_doppler,inventario}.py`, `normalizacion.py` | C4 ✅ | ⚠️ Reconstruida desde `e82796d`: inventario Eco y pruebas de página/omisión entraron juntos. | Medida y sección omitida, página distinta, tabla de dos columnas. | Inventario por página y ordinal. |
| 3.5 | `tests/pipeline/test_ejecutor.py`, `tests/integracion/test_lote_aislamiento.py`, `tests/salida/test_cuarentena.py` / `pipeline/{ejecutor,etapas}.py`, `salida/{cuarentena,modelos_orm}.py`, migración `0002_metadata_segura_cuarentena.py` | C5 ✅ | ⚠️ Reconstruida desde `b16eee0`: pruebas de bloqueo/aislamiento/cuarentena y la integración entraron juntas. | Bloqueo antes de PII, lote aislado y metadata segura persistida. | Etapa explícita y migración mínima de `campo`/`pagina`. |
| 4.1 | `tests/reconciliacion/test_ecg_mortara.py`, `tests/reconciliacion/test_eco_doppler.py` / — | C2 y C4 ✅ | ⚠️ Reconstruida desde `e74e22d`: casos cruzados añadidos con el correctivo; no hay ejecución RED histórica. | ECG cruzado, nombre Eco fuera de header y firma separada. | Casos de asociación junto a cada layout. |
| 4.2 | mismas pruebas de 4.1 / `reconciliacion/{_comun,ecg_mortara,eco_doppler}.py` | C2 y C4 ✅ | ⚠️ Reconstruida desde `e74e22d`: validadores selector→etiqueta→valor y pruebas modificados juntos. | Etiqueta vecina ECG, ejes multilinea y firma en líneas separadas. | Asociación estructurada compartida. |
| 4.3 | pruebas de 4.1 / mismos módulos | C2 y C4 ✅; C6 ✅ | ⚠️ Reconstruida desde `e74e22d`: el commit contiene pruebas y refactor; PR separado verificable en historial. | Normalizaciones y errores seguros conservados por suites ECG/Eco. | Sin ampliar metadata ni alterar normalizaciones permitidas. |
| 5.1 | `tests/reconciliacion/test_eco_doppler.py` / — | `pytest -q tests/reconciliacion/test_eco_doppler.py tests/reconciliacion/test_inventario.py` ✅ 28 passed | ✅ Contemporánea: las dos pruebas de selector específico/asignación cruzada fallaron antes del cambio, según registro del PR 10. | Tabla de dos columnas, dos etiquetas y mismo valor. | ➖ No necesario. |
| 5.2 | `tests/reconciliacion/test_eco_doppler.py` / `dominio/referencias.py`, `reconciliacion/base.py`, `parseo/eco_doppler.py`, `reconciliacion/eco_doppler.py` | misma suite focalizada ✅ 28 passed | ✅ Contemporánea: selector genérico emitido y específico rechazado antes del cambio, según registro del PR 10. | Selectores clínicos `ao`/`ai` y cruce de referencias. | Selector normalizado centralizado. |
| 5.3 | `tests/reconciliacion/test_inventario.py` / `reconciliacion/eco_doppler.py` | misma suite focalizada ✅ 28 passed | ✅ Contemporánea: faltaba whitelist Eco; el test falló antes del ajuste, según registro del PR 10. | Boilerplate permitido y patrón clínico sin destino rechazado. | Whitelist local e inmutable. |
| 5.4 | este archivo / — | Revisión documental de las 21 filas y C6 ✅ | ✅ Contemporánea para formato inicial; reconstrucción ampliada para 1.1–4.3. | Archivos, comandos y estado diferenciado por cada tarea. | Sin duplicar contenido clínico ni PII. |
| 5.5 | `verify-report.md`, `tasks.md` / — | C6 ✅ 344 passed | ✅ Contemporánea: `git diff --check main...HEAD` detectó espacios finales previos; se registró su limpieza en PR 10. | Suite focalizada, suite completa y chequeo de formato. | Espacios finales eliminados del informe. |

## Tareas completadas

- [x] 1.1–1.4 Contratos, normalización y seguridad de metadata.
- [x] 2.1–2.4 Strategies de ECG, laboratorio, Eco y registro.
- [x] 3.1–3.5 Inventario independiente y bloqueo del pipeline.
- [x] 4.1–4.3 Asociación exacta etiqueta→valor.
- [x] 5.1–5.5 Corrección final Eco, whitelist y verificación.

## Resultado acumulado

- Pruebas focalizadas de reconstrucción: C1–C5, todas verdes.
- Suite completa: C6, **344 passed**.
- No se modificó código de producción ni pruebas durante esta reconstrucción.
- La evidencia de RED de tareas 1.1–4.3 es reconstruida y está marcada como tal; las tareas 5.1–5.5 preservan evidencia contemporánea.
