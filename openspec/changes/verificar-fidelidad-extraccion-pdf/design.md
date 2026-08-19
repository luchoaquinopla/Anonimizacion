# Diseño: Verificar fidelidad de extracción desde PDF

## Enfoque técnico

`reconciliacion` se ejecutará entre `parseo` y `deteccion_pii`. Comprueba dos propiedades independientes: (1) cada valor emitido tiene evidencia única y semánticamente igual en el PDF; (2) todo dato clínico reconocible inventariado desde el PDF tiene exactamente un destino en `DocumentoParseado`. Ninguna comprobación de cobertura puede derivarse solo de `documento.fuentes` ni de los valores ya parseados.

## Decisiones de arquitectura

| Decisión | Elección y motivo |
|---|---|
| Inventario independiente | Cada `InventariadorDocumento` Strategy lee `TextoExtraido` y produce hallazgos declarativos por tipo, antes de consultar el modelo. Reutiliza etiquetas/layout, pero no el resultado del parser: evita que una omisión se autoapruebe. |
| Hallazgo seguro | `HallazgoCobertura(id_campo, pagina, ordinal, clase)` no lleva texto, valor, nombre, DNI ni hash. `id_campo`/`clase` pertenecen a whitelist y `ordinal` preserva el orden de colecciones. |
| Correspondencia | El reconciliador construye las claves `(id_campo, ordinal)` de inventario y de modelo/referencias; exige igualdad uno-a-uno. Para laboratorio y eco además comprueba cardinalidad y ordinal, por lo que filas/secciones duplicadas u omitidas no se esconden por nombre o valor repetido. |
| Texto ignorado | Whitelist declarativa por tipo para boilerplate/encabezados visuales. Solo se ignora lo incluido allí; un patrón clínico reconocido sin destino causa cobertura incompleta. Texto desconocido no se convierte implícitamente en clínico ni se persiste. |
| Fallo seguro | Nuevos códigos de cobertura se propagan como `ErrorParseo` no reintentable con campo/página. Cuarentena conserva solo esa metadata; no almacena valores, fragmentos, PII ni huellas. |

## Flujo de datos

```text
PDF -> TextoExtraido -> parser -> DocumentoParseado + ReferenciaCampo
       |                                      |
       +-> Inventariador Strategy ------------+
                         -> igualdad + cobertura 1:1
                         -> aprobado -> deteccion_pii -> pseudonimizacion -> salida
                         -> ErrorParseo(reconciliacion) -> cuarentena
```

`EjecutorPipeline._resolver_documento` obtendrá el reconciliador y lo ejecutará inmediatamente tras `parsear`, dentro de `_ejecutar_con_reintentos`. Al fallar, el documento no llega a PII, claves, episodios ni escritor. ECG inventaría headers y medidas; laboratorio, cada fila clínica por sección/ordinal; eco, medidas y secciones de texto por página/ordinal. ECG usa `paginas`; laboratorio y eco, `paginas_ordenadas`.

## Cambios de archivos

| Archivo | Acción | Descripción |
|---|---|---|
| `src/anonimizacion/reconciliacion/base.py` | Modificar | Añadir `HallazgoCobertura`, `InventariadorDocumento` y contratos de cobertura seguros. |
| `src/anonimizacion/reconciliacion/inventario.py` | Crear | Algoritmo común: validar whitelist, claves, correspondencia uno-a-uno y cardinalidad. |
| `src/anonimizacion/reconciliacion/{ecg_mortara,laboratorio_general,eco_doppler}.py` | Modificar | Implementar inventarios independientes y reglas de asociación selector-etiqueta-valor. |
| `src/anonimizacion/reconciliacion/_comun.py` | Modificar | Mantener igualdad campo→PDF; combinarla con cobertura PDF→modelo, sin contar valores sueltos. |
| `src/anonimizacion/dominio/{referencias,errores}.py` | Modificar | Declarar IDs/clases/whitelists permitidos y códigos `COBERTURA_INCOMPLETA`/`COBERTURA_AMBIGUA`. |
| `src/anonimizacion/parseo/{ecg_mortara,laboratorio_general,eco_doppler}.py` | Modificar | Emitir referencias completas y ordinales coherentes con el contrato, sin duplicar inventario. |
| `src/anonimizacion/pipeline/{etapas,ejecutor}.py` | Modificar | Registrar etapa y ejecutar reconciliación antes de PII. |
| `tests/reconciliacion/`, `tests/pipeline/` | Crear/Modificar | Cobertura sintética e integración de bloqueo/cuarentena. |

## Contratos

```python
@dataclass(frozen=True)
class HallazgoCobertura:
    id_campo: str       # ruta permitida; nunca contenido
    pagina: int         # base 1
    ordinal: int = 0    # posición estable de colección
    clase: str = "dato" # clase permitida

class InventariadorDocumento(Protocol):
    tipo_documento: TipoDocumento
    def inventariar(self, texto: TextoExtraido) -> tuple[HallazgoCobertura, ...]: ...
```

`ReconciliadorDocumento.reconciliar(documento, texto)` primero obtiene el inventario y verifica sus claves únicas; luego cruza inventario con destinos esperados del modelo y con `ReferenciaCampo`. Diferencia: `ReferenciaCampo` es procedencia de un valor emitido; `HallazgoCobertura` es una observación independiente del PDF. Un hallazgo sin destino genera `COBERTURA_INCOMPLETA`; claves repetidas o desordenadas, `COBERTURA_AMBIGUA`.

## Estrategia de pruebas

| Capa | Prueba TDD |
|---|---|
| Unit | RED para inventario ECG completo/medida omitida; laboratorio con fila repetida/omitida; eco con medida o sección faltante. Fixtures solo sintéticas. |
| Unit | Whitelist: boilerplate permitido no exige destino; patrón clínico reconocido fuera de ella falla. Igualdad valida selector y asociación, no mera presencia del valor. |
| Integración | Aprobado invoca PII; igualdad o cobertura fallida no invoca PII, claves, vínculo ni salida y produce cuarentena sin contenido. |

## Migración y rollout

No requiere migración de datos: la metadata existente de cuarentena (`campo`, `pagina`, código) es suficiente. Activación obligatoria; no se reprocesan registros existentes. Rollback revierte código/configuración, sin alterar dataset emitido.

## Preguntas abiertas

Ninguna. Las huellas de trazabilidad no se persistirán en esta fase.
