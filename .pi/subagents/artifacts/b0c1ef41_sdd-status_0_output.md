## Resultado SDD

**Estado:** `blocked`  
**Selección activa:** `ingesta-pdf-clinicos`, seleccionada explícitamente por la solicitud y validada en OpenSpec.  
**skill_resolution:** `fallback-path` (contrato global: `~/.pi/agent/gentle-ai/support/sdd-status-contract.md`).

```yaml
schemaName: spec-driven
changeName: ingesta-pdf-clinicos
artifactStore: openspec
planningHome:
  root: D:/proyectos/anonimizacion/openspec
  changesDir: D:/proyectos/anonimizacion/openspec/changes
changeRoot: D:/proyectos/anonimizacion/openspec/changes/ingesta-pdf-clinicos
artifactPaths:
  proposal:
    - openspec/changes/ingesta-pdf-clinicos/proposal.md
  specs:
    - openspec/changes/ingesta-pdf-clinicos/specs/calidad-de-extraccion/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/carga-manual-local/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/datasets-ml-derivados/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/ingesta-clinica-anonimizada/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/observaciones-clinicas/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/validacion-privacidad-y-calidad/spec.md
  design:
    - openspec/changes/ingesta-pdf-clinicos/design.md
  tasks:
    - openspec/changes/ingesta-pdf-clinicos/tasks.md
  applyProgress:
    - openspec/changes/ingesta-pdf-clinicos/apply-progress.md
  verifyReport:
    - openspec/changes/ingesta-pdf-clinicos/verify-report.md
  syncReport:
    - openspec/changes/ingesta-pdf-clinicos/sync-report.md
contextFiles:
  proposal: [openspec/changes/ingesta-pdf-clinicos/proposal.md]
  specs:
    - openspec/changes/ingesta-pdf-clinicos/specs/calidad-de-extraccion/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/carga-manual-local/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/datasets-ml-derivados/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/ingesta-clinica-anonimizada/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/observaciones-clinicas/spec.md
    - openspec/changes/ingesta-pdf-clinicos/specs/validacion-privacidad-y-calidad/spec.md
  design: [openspec/changes/ingesta-pdf-clinicos/design.md]
  tasks: [openspec/changes/ingesta-pdf-clinicos/tasks.md]
  applyProgress: []
  verifyReport: []
  syncReport: []
artifacts:
  proposal: done
  specs: done
  design: done
  tasks: done
  applyProgress: missing
  verifyReport: missing
  syncReport: missing
taskProgress:
  total: 16
  complete: 0
  remaining: 16
  unchecked:
    - "tasks.md:36 — RED: crear pruebas unitarias de estados, inventario y rechazo."
    - "tasks.md:37 — GREEN: tipos puros y política de decisión efímera."
    - "tasks.md:38 — TRIANGULATE: casos de valores/unidades/candidatos."
    - "tasks.md:39 — REFACTOR: aislar dominio y documentar comprobador."
    - "tasks.md:43 — RED: pruebas de adaptador de laboratorio."
    - "tasks.md:44 — GREEN: extractor PyMuPDF y puerto FamilyAdapter."
    - "tasks.md:45 — TRIANGULATE: orden variable, tablas incompletas y candidatos."
    - "tasks.md:46 — REFACTOR: aislar mapeo y excluir pdfplumber/OCR."
    - "tasks.md:50 — DocumentSource, PrivacyValidator y validador residual."
    - "tasks.md:51 — Entrada local mínima en bootstrap."
    - "tasks.md:52 — Documentar evidencia del spike."
    - "tasks.md:58 — Evaluador de calidad posterior a corpus aprobado."
    - "tasks.md:59 — Conectar evaluación a habilitación."
    - "tasks.md:65 — Persistencia aprobada, migraciones e integración."
    - "tasks.md:66 — Adaptadores de ecocardiografía y ECG."
    - "tasks.md:67 — Derivación versionada de features."
deferredParentActions:
  total: 2
  complete: 0
  remaining: 2
  unchecked:
    - "tasks.md:71 — Revisión acotada del PR 1."
    - "tasks.md:72 — Decisión de entrega por riesgo alto antes de PR 2/PR 3."
taskArtifactErrors: []
applyState: blocked
dependencies:
  apply: blocked
  verify: blocked
  sync: blocked
  archive: blocked
actionContext:
  mode: repo-local
  workspaceRoot: D:/proyectos/anonimizacion
  allowedEditRoots:
    - D:/proyectos/anonimizacion
  warnings: []
nextRecommended: "Resolver la decisión de entrega (cadena de PRs o excepción al presupuesto de 400 líneas) y reconciliar propuesta/diseño/tareas a un único alcance antes de iniciar sdd-apply."
isNonAuthoritative: false
```

### Hallazgos / riesgos

- **BLOCKER — alcance inconsistente:** `proposal.md:13-19,45` exige UI local de navegador y adaptadores de laboratorio, ecocardiografía y ECG; `tasks.md:21,32-52` limita el primer incremento a un spike local de laboratorio, sin persistencia; `design.md:5,8-12,23-24,38-40` todavía prescribe PostgreSQL, cola y datasets.
- **BLOCKER — decisión de entrega pendiente:** `tasks.md:7-17` estima **650–1.000 líneas**, excede el presupuesto de revisión de 400, recomienda PRs encadenados y mantiene `Chain strategy: pending`.
- **CRITICAL para archivo:** 16 tareas de implementación sin completar; además no existen `apply-progress.md`, `verify-report.md` ni `sync-report.md`.
- **Riesgo residual alto:** aprobaciones de corpus, inventarios, umbrales, fuente autorizada y privacidad siguen pendientes (`tasks.md:27-30`; `design.md:63-71`).