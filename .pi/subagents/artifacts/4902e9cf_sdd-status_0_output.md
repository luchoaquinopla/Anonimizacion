## Informe SDD — estado autoritativo

**Estado:** `blocked`  
**Fase siguiente exacta lista:** **`sdd-tasks`** (crear `tasks.md`).  
**Selección:** cambio indicado explícitamente: `ingesta-pdf-clinicos`.  
**Resolución de habilidad:** `none` (no se inyectaron rutas y no existe contrato de soporte instalado accesible).

```json
{
  "schemaName": "gentle-ai/sdd-status/v1",
  "changeName": "ingesta-pdf-clinicos",
  "artifactStore": "both",
  "planningHome": "openspec",
  "changeRoot": "openspec/changes/ingesta-pdf-clinicos",
  "artifactPaths": {
    "proposal": "openspec/changes/ingesta-pdf-clinicos/proposal.md",
    "specs": [
      "openspec/changes/ingesta-pdf-clinicos/specs/calidad-de-extraccion/spec.md",
      "openspec/changes/ingesta-pdf-clinicos/specs/datasets-ml-derivados/spec.md",
      "openspec/changes/ingesta-pdf-clinicos/specs/ingesta-clinica-anonimizada/spec.md",
      "openspec/changes/ingesta-pdf-clinicos/specs/observaciones-clinicas/spec.md"
    ],
    "design": "openspec/changes/ingesta-pdf-clinicos/design.md",
    "tasks": "openspec/changes/ingesta-pdf-clinicos/tasks.md",
    "applyProgress": "openspec/changes/ingesta-pdf-clinicos/apply-progress.md",
    "verifyReport": "openspec/changes/ingesta-pdf-clinicos/verify-report.md",
    "syncReport": "openspec/changes/ingesta-pdf-clinicos/sync-report.md"
  },
  "contextFiles": [
    "AGENTS.md"
  ],
  "artifacts": {
    "proposal": "present",
    "specs": "present (4)",
    "design": "present",
    "tasks": "missing",
    "applyProgress": "missing",
    "verifyReport": "missing",
    "syncReport": "missing",
    "engram": {
      "proposal": "present",
      "spec": "present",
      "design": "present",
      "tasks": "not found"
    }
  },
  "taskProgress": {
    "total": 0,
    "implementationTotal": 0,
    "implementationCompleted": 0,
    "implementationUnchecked": 0,
    "unchecked": [],
    "taskArtifactErrors": []
  },
  "applyState": "not_started",
  "dependencies": {
    "tasks": "ready",
    "apply": "blocked",
    "verify": "blocked",
    "sync": "blocked",
    "archive": "blocked"
  },
  "actionContext": {
    "mode": "repo-local",
    "workspaceRoot": "D:/proyectos/anonimizacion",
    "safe": true
  },
  "nextRecommended": "sdd-tasks",
  "blockedReasons": [
    "Falta el artefacto de tareas: openspec/changes/ingesta-pdf-clinicos/tasks.md.",
    "Sin tareas no es posible determinar trabajo de implementación ni habilitar apply.",
    "No hay evidencia de apply, verificación ni sincronización."
  ],
  "isNonAuthoritative": false
}
```

### Hallazgos de revisión
- **Blocker:** `openspec/changes/ingesta-pdf-clinicos/tasks.md` no existe; la implementación no puede iniciar conforme al contrato SDD.
- **Alta:** `proposal.md` y `design.md` dejan pendientes fuente autorizada, broker, corpus/inventarios/umbrales y decisión de seudonimización; deberán traducirse en tareas y/o acciones parentales explícitas.
- **Riesgo residual:** la propuesta identifica riesgo alto de omisión clínica y riesgo medio de PII residual; no existe aún evidencia de validación ejecutada.
- No se modificaron archivos. No hay archivos en staging; `.pi/` aparece como no rastreado, fuera del alcance de esta revisión.