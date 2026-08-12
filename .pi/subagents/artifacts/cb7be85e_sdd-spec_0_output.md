status: completed

executive_summary: >
  Se alinearon las cuatro especificaciones existentes con la propuesta aprobada y
  se añadieron las capacidades `carga-manual-local` y
  `validacion-privacidad-y-calidad`. Las specs eliminan obligaciones de
  persistencia y ML, y fijan procesamiento síncrono en memoria, descarte total,
  puerto de entrada desacoplado y acuse seguro al finalizar el lote.

artifacts:
  - `openspec/changes/ingesta-pdf-clinicos/specs/carga-manual-local/spec.md` — nueva
  - `openspec/changes/ingesta-pdf-clinicos/specs/validacion-privacidad-y-calidad/spec.md` — nueva
  - `openspec/changes/ingesta-pdf-clinicos/specs/ingesta-clinica-anonimizada/spec.md` — actualizada
  - `openspec/changes/ingesta-pdf-clinicos/specs/observaciones-clinicas/spec.md` — actualizada
  - `openspec/changes/ingesta-pdf-clinicos/specs/datasets-ml-derivados/spec.md` — reformulada como exclusión explícita
  - `openspec/changes/ingesta-pdf-clinicos/specs/calidad-de-extraccion/spec.md` — actualizada
  - Engram: `sdd/ingesta-pdf-clinicos/spec`, observación `548`

next_recommended:
  - Ejecutar la fase de diseño para reconciliar `design.md` con las specs aprobadas.
  - Después, actualizar `tasks.md`; no iniciar implementación usando sus obligaciones actuales.

risks:
  - "**Alta — `openspec/changes/ingesta-pdf-clinicos/design.md`:** sigue prescribiendo PostgreSQL, colas/workers, persistencia y datasets ML, en conflicto directo con la propuesta y las specs."
  - "**Alta — `openspec/changes/ingesta-pdf-clinicos/tasks.md`:** todavía incluye persistencia, migraciones, broker, CLI y derivación de features; no debe guiar implementación hasta actualizarse."
  - "**Media — códigos técnicos:** la taxonomía segura sigue siendo una dependencia pendiente; las specs fijan sus propiedades de privacidad, pero no inventan códigos concretos."

skill_resolution: none