# Proposal: Verificar fidelidad de extracción desde PDF

## Intent
Impedir que un valor alterado, truncado o asignado al campo equivocado llegue a anonimización o persistencia. Cada documento debe reconciliar su registro tipado contra la evidencia extraída del PDF antes de que la PII sea tratada.

## Scope

### In Scope
- Nueva etapa `reconciliacion` entre `parseo` y `deteccion_pii` para ECG, laboratorio y eco.
- Contrato de evidencia por campo: valor normalizado, ubicación/fuente y regla de comparación; admite equivalencias explícitas de formato, nunca cambios semánticos.
- Fallo determinístico a cuarentena ante campo requerido ausente, discrepancia, duplicado ambiguo o evidencia insuficiente; trazabilidad auditable sin PII ni valores clínicos crudos.
- Pruebas TDD con fixtures sintéticas: coincidencia, normalización permitida y cada clase de discrepancia.

### Out of Scope
- Corregir automáticamente valores discrepantes, OCR o nuevos layouts.
- Persistir texto fuente, PII o valores clínicos crudos como evidencia de cuarentena.
- Reprocesar registros ya emitidos; se hará como operación separada con los originales cifrados.

## Capabilities

### New Capabilities
- `reconciliacion-extraccion`: valida que cada dato estructurado provenga fielmente del contenido fuente del PDF antes de continuar el pipeline.

### Modified Capabilities
- None. Las especificaciones base aún no fueron archivadas en `openspec/specs/`; esta capacidad nueva define su integración con parseo y procesamiento por lote.

## Approach
Los parsers conservarán procedencia no sensible por campo (identificador de campo, página, coordenada/selector y huella HMAC de la representación normalizada). Un reconciliador común aplicará reglas declarativas por tipo de documento y comparará en memoria el valor tipado contra su evidencia en `TextoExtraido`. Solo un resultado aprobado puede pasar a PII, pseudonimización y salida. Un fallo será `ErrorParseo` no reintentable y cuarentena conservará únicamente documento, tipo, etapa, código, campo y localización, nunca contenido.

Los tres PDFs proporcionados confirman texto nativo y layouts ECG de 1 página, eco de 2 y laboratorio de 3; se usarán solo para calibración local, sin versionarlos ni copiar sus datos.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `src/anonimizacion/reconciliacion/` | New | Contratos, reglas y validador común. |
| `src/anonimizacion/parseo/` | Modified | Procedencia de campos por parser. |
| `src/anonimizacion/pipeline/` | Modified | Etapa y aislamiento antes de PII. |
| `src/anonimizacion/dominio/`, `salida/` | Modified | Código seguro y metadatos de cuarentena. |
| `tests/` | Modified | Casos sintéticos de fidelidad. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Layout no cubierto | Medium | Reglas por Strategy, cuarentena y fixtures representativas. |
| Evidencia filtra datos | Low | Whitelist de metadata + HMAC con clave separada; prohibir valores crudos. |
| Normalización oculta un cambio | Medium | Equivalencias explícitas, testeadas y acotadas por campo. |

## Rollback Plan
Desactivar la nueva etapa mediante configuración y revertir el cambio; los documentos fallidos permanecen aislados y los datos ya emitidos no se modifican.

## Dependencies
- PDFs originales cifrados disponibles para revisión autorizada.
- Pepper/clave HMAC separada del dataset y de cuarentena.

## Success Criteria
- [ ] Ningún documento se anonimiza ni persiste sin reconciliación aprobada.
- [ ] Toda discrepancia conocida termina en cuarentena sin datos sensibles.
- [ ] Tests sintéticos cubren ECG, laboratorio y eco con igualdad y fallos.
