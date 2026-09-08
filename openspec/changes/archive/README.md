# Convención de archivo de cambios openspec

No existía una convención previa en este repo (el directorio `archive/` existía vacío, sin
ningún cambio archivado todavía). Se establece acá, aplicada de forma consistente:

## Cuándo se archiva un cambio

Un cambio se archiva sólo cuando su implementación está **verificada contra el código real en
`main`** (no contra su propio `tasks.md`, que puede estar desactualizado). "Verificado" significa
que se comprobó, por lectura directa de `src/`/`migrations/` y por `git log`, que los módulos,
migraciones y comportamientos que el cambio describe existen y están mergeados — no que el
checklist tiene todas las casillas marcadas.

Un cambio con tareas pendientes reales (no placeholders documentados como fuera de alcance) queda
abierto en `openspec/changes/`, con lo que le falta listado explícitamente en el reporte que lo
audita.

## Qué se hace al archivar

1. Mover el directorio completo del cambio a `openspec/changes/archive/<nombre>/` (con
   `git mv` para preservar el historial de cada archivo).
2. Si el cambio agrega o modifica una capability cuya spec base ya es archivable (no depende de
   un cambio todavía abierto), fusionar su spec delta en `openspec/specs/<capability>/spec.md`
   — el spec "vigente" consolidado, fuera de cualquier directorio de cambio. Una capability cuyo
   delta modifica la spec de un cambio que sigue abierto (ver más abajo) no se fusiona todavía:
   viaja archivada junto a su cambio hasta que la base se archive.
3. Si el cambio no llegó a tener spec delta propia (se implementó directo desde la propuesta,
   sin pasar por `sdd-spec`), se archiva igual si el código está verificado, dejando constancia
   de que no hay spec delta que fusionar.

## Archivado el 2026-09-08

Verificado contra el código real en `main` (suite completa `pytest -q`: 864 passed, 1 skipped
por falta de privilegio de symlink en Windows; `ruff check .`: sin hallazgos):

- **`pdf-pii-anonymization`** — pipeline base completo (dominio, ingesta, extracción, detección,
  parseo, PII, pseudonimización, salida, ejecutor, trabajadores, observabilidad). Se corrigieron
  tres requisitos que habían quedado `BLOQUEADO`/desactualizados antes de fusionar sus specs:
  formato de salida (resuelto: PostgreSQL, no Parquet — ver `3410d6c`), almacenamiento del salt
  (resuelto: `ANONIMIZACION_PEPPER`/`ANONIMIZACION_PEPPER_ARCHIVO`) y política del nombre del
  médico derivante (resuelto: namespace `id_medico` propio). Specs fusionadas: 7 capabilities.
- **`escritura-idempotente`** — `clave_documento` HMAC, restricción única en `estudio`,
  guarda de dos capas contra reprocesamiento. Se retiraron los Requisitos 4 (reformulado) y 5
  (retirado) de su spec: describían el manifiesto/Parquet de `PublicadorBundles`, eliminado en
  `3410d6c` sin llamador de producción. Tarea 12.3 de `tasks.md` queda parcial (invariante de
  carga no verificable contra el banco actual, que usa un destino en memoria) pero documentada
  como hallazgo propio para un cambio futuro, no como trabajo pendiente de éste.
- **`hora-de-estudio`** — campo `hora_estudio`/`precision_hora` de primera clase, spec ya sin
  referencias a Parquet/bundles. Spec fusionada sin cambios.
- **`panel-de-operacion`** — embudo de corrida, portal WSGI real, observabilidad cableada.
  `tasks.md` completo (Fases 1-10). Se fusionaron `panel-de-operacion` y `trazabilidad-por-corrida`
  (capabilities nuevas, autocontenidas) y el delta de `escritura-idempotente` (Requisito 8, ver
  `openspec/specs/escritura-idempotente/spec.md`). El delta de `portal-de-corridas` **no** se
  fusionó: modifica la spec base de esa capability, que vive en
  `openspec/changes/operacion-segura-y-escalable/` — todavía abierto (ver más abajo) — así que
  viaja archivada junto a este cambio hasta que esa base se archive.
- **`paralelismo-de-procesamiento`** — despacho multiproceso (`despacho_paralelo.py`),
  agrupamiento por subcarpeta, correcciones de `IntegrityError`/pool contra RDS. Sin spec delta
  propia (se implementó directo desde la propuesta vía PR #38 y correcciones posteriores);
  verificado por lectura de `src/anonimizacion/trabajadores/despacho_paralelo.py` y por
  `git log --grep=paralelo`. El riesgo de "colisión de identidad entre grupos" que su propia
  propuesta declara **NO mitigado** sigue abierto — ver la nota separada sobre
  `feat/colision-de-identidad-entre-grupos` en el reporte de esta auditoría.
- **`procesamiento-por-grupo`** — el grupo (no el documento ni la carpeta) como unidad de
  trabajo, motivos de cuarentena distinguibles por episodio vs. campo. Sin `tasks.md` propio
  (diseño + spec, implementado como parte de PR #23); verificado por lectura de
  `pipeline/ejecutor.py`/`coordinador_episodios.py` y por `git log`.
- **`puerto-de-ingesta`** — `Protocol FuenteDeArtefactos`, `FuenteLocal` perezosa con
  deduplicación y cuarentena por sobretamaño. `tasks.md` completo (Fases 1-9).
- **`verificar-fidelidad-extraccion-pdf`** — reconciliación 1:1 modelo↔PDF para los tres tipos
  de documento. `tasks.md` completo (Fases 1-6).
- **`escritura-por-lotes`** — **no implementada, archivada como investigación descartada.**
  Nunca llegó a versionarse en git (quedó como directorio sin seguimiento). Ver la conclusión de
  archivo agregada a su `proposal.md`: la medición real contra Postgres (6,67 round trips por
  documento, no los ~22 que sugería una medición previa contra SQLite) mostró que la ganancia
  proyectada (~20-30% menos viajes) no justificaba el riesgo de `SAVEPOINT`/sesión compartida
  frente al ~82-88% que capturó `paralelismo-de-procesamiento` con menos riesgo. Reemplazada por
  esa propuesta, que lo dice explícitamente.

## Qué queda abierto y por qué

`openspec/changes/operacion-segura-y-escalable/` permanece sin archivar: tiene tareas reales
pendientes en `tasks.md` (4.3c — escalón de 100k, 4.4/4.5 — diagnóstico y corrección de eco,
4.6b — bitácora de Obsidian, y toda la Fase 5 de verificación). Su requisito de Parquet/bundles
en `specs/bundles-anonimizados/spec.md` ya se cerró con traza completa (ver ese archivo) aunque
el cambio en sí siga abierto — cerrar un requisito que miente no espera a que el resto del cambio
termine.
