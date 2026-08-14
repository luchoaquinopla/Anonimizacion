# Progreso de aplicación: PR 2 — privacidad y límites operativos

## Estado consumido

- Cambio: `ingesta-pdf-clinicos`; `apply=ready`.
- Contexto de acción: `repo-local`, raíz autorizada `D:\proyectos\anonimizacion`; sin advertencias.
- Alcance aplicado: sólo PR 2. No se inició PR 3/UI, persistencia, calidad habilitable ni otras familias.

## Ciclos TDD

| Ciclo | Evidencia RED | Evidencia GREEN | Evidencia TRIANGULATE / REFACTOR |
| --- | --- | --- | --- |
| Privacidad residual | `tests/test_flujo_privacidad_pr2.py` falló inicialmente: 4 fallos por dependencias no inyectables y excepciones sin convertir. | Se inyectan anonimización y validación; el hallazgo residual y los campos requeridos no verificables devuelven sólo códigos seguros. | Se cubrieron los fallos de extracción y validación aplicables sin lote; TRIANGULATE queda satisfecho sólo para esos casos porque PR 2 no implementa procesamiento por lote. La cobertura de lote parcial se difiere explícitamente a PR 3. La comprobación de dependencias laterales prohibidas permanece verde. |

## Trabajo completado

- Se añadió una etapa explícita de anonimización antes de la validación residual independiente.
- `PuertoEntradaIngesta` acepta un validador y un anonimizador inyectables, aplica controles de campos obligatorios reales y convierte fallos de extracción o validación en rechazos técnicos seguros.
- Las referencias transitorias se liberan en el flujo de éxito y error; la salida conserva sólo decisión, códigos y conteos.
- Se actualizaron inmediatamente las casillas completadas de RED, GREEN, TRIANGULATE aplicable sin lote, REFACTOR y cierre de PR 2 en `tasks.md`; la cobertura de lote parcial queda planificada en PR 3.
- Se corrigió la evidencia de cierre de PR 1: el 2026-08-14 se confirmaron 25 pruebas aprobadas con el comando indicado y árbol limpio.

## Archivos modificados

- `src/ingesta_clinica/dominio/privacidad.py`
- `src/ingesta_clinica/aplicacion/puertos/entrada.py`
- `src/ingesta_clinica/composicion.py`
- `tests/test_flujo_privacidad_pr2.py`
- `openspec/changes/ingesta-pdf-clinicos/tasks.md`
- `openspec/changes/ingesta-pdf-clinicos/apply-progress.md`

## Verificación

| Comando | Resultado |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/test_flujo_privacidad_pr2.py -q` | 6 aprobadas |
| `.venv/Scripts/python.exe -m pytest -q` | 31 aprobadas |
| `git diff --check` | sin errores de espacios |

## Desviaciones y limitaciones

- No hay implementación de procesamiento por lote en PR 2; por tanto su TRIANGULATE sólo queda satisfecho para los errores de extracción y validación aplicables sin lote. La cobertura de lote parcial se difiere a PR 3 y no se declara implementada.
- La anonimización es deliberadamente mínima y limitada a marcadores sintéticos; no declara cobertura clínica ni aptitud productiva.
- No se añadieron archivos, registros de contenido, base de datos, migraciones, colas, *brokers*, red ni UI.

## Trabajo restante

- PR 3 debe cubrir explícitamente el lote parcial junto con archivos no laboratorio, errores por archivo y lotes mixtos; no se inició esa cobertura en PR 2.
- PR 3/UI y todas las tareas tras sus puertas permanecen fuera de alcance.
- Acciones de ciclo de vida diferidas al padre: revisión del tamaño del diff de PR 2 y todas las puertas de calidad, persistencia, ecocardiografía, ECG y ML.

## Límite de revisión

El cambio se mantiene bajo el presupuesto de 400 líneas para el PR 2; su límite es privacidad y descarte en memoria. No se creó commit, push ni recibo de entrega.
