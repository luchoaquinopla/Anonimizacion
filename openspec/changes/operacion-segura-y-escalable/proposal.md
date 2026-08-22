# Proposal: operación segura y escalable

## Intent

Convertir el pipeline local en un servicio capaz de procesar miles de PDFs sin perder agrupación por episodio. También se necesita validar sin datos reales.

## Scope

### In Scope
- Portal interno para iniciar y consultar corridas; secretos, originales y procesamiento permanecen en el servidor institucional.
- Orquestación por corrida/episodio: inventario persistente, extracción mínima, vínculo temporal, paralelismo y ensamblado final.
- Bundles pseudónimos con manifiesto y Parquet, sin PDFs crudos.
- Telemetría de cuarentena y corrección del eco desde un caso reproducible.
- Generador local y reproducible de PDFs sintéticos equivalentes a ECG, laboratorio y eco, con oráculo y carga.

### Out of Scope
- Cinecoronariografía sin muestra y parser.
- Modelos clínicos, API pública o Kubernetes.
- Relajar reconciliación para aceptar documentos de eco no verificables.

## Capabilities

### New Capabilities
- `portal-de-corridas`: iniciar y consultar corridas internas.
- `orquestacion-de-episodios`: coordinación durable por episodio.
- `bundles-anonimizados`: salida por episodio y Parquet idempotente.
- `corpus-sintetico-clinico`: PDFs sintéticos, oráculo, validación y carga.
- `diagnostico-de-cuarentena`: métricas sin PII de rechazos.

### Modified Capabilities
- None; aún no hay especificaciones base.

## Approach

La web sólo solicita y observa corridas. Un orquestador persistirá inventario/estado en PostgreSQL, paralelizará pasos por PDF y ensamblará episodios tras resolver identidad y ventana temporal; no dependerá de tareas Celery aisladas. Reconciliación precederá anonimización y salida. Cada episodio aprobado emitirá `id_paciente/id_episodio/manifest.json`, datos seguros y Parquet; originales y cuarentena quedarán fuera del dataset.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `src/anonimizacion/pipeline/` | Modified | Corridas y ensamblado durable |
| `src/anonimizacion/{ingesta,salida,trabajadores}/` | Modified | Estados, proyecciones, paralelismo |
| `src/anonimizacion/parseo/eco_doppler.py` | Modified | Corrección guiada por evidencia |
| `tests/` | New/Modified | Corpus sintético y carga |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Agrupación incorrecta | High | Commit tras ensamblado durable |
| PII en salida o diagnóstico | Medium | IDs HMAC, métricas sin PII y separación física |
| Variante de eco desconocida | Medium | Fixture mínima y TDD; mantener cuarentena |

## Rollback Plan

Mantener el proceso actual para lotes controlados. Deshabilitar portal/orquestador, detener corridas y revertir proyecciones idempotentes; preservar auditoría, cuarentena y originales cifrados.

## Dependencies

- Infraestructura: PostgreSQL, secretos, almacenamiento cifrado, permisos y respaldo.
- Muestra anonimizada o diagnóstico seguro del eco.

## Success Criteria

- [ ] Una corrida masiva se reanuda tras interrupción sin duplicar episodios ni emitir PII.
- [ ] Cada episodio aprobado produce bundle pseudónimo, manifiesto y Parquet trazable.
- [ ] El corpus cubre casos válidos, ambiguos, faltantes y corruptos.
- [ ] El portal no procesa ni almacena secretos ni PDFs en el navegador.
