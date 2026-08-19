# Design: Verificar fidelidad de extracción desde PDF

## Technical Approach

Se agrega `reconciliacion` entre `parseo` y `deteccion_pii`. Los tres parsers seguirán siendo Strategies y, junto al `DocumentoParseado`, declararán referencias por campo a la página y selector de texto que los originó. Un reconciliador registrado por `TipoDocumento` vuelve a localizar cada evidencia sobre `TextoExtraido`, normaliza ambos lados y decide. No corrige valores: ante cualquier duda lanza un `ErrorParseo` determinístico, por lo que el ejecutor ya existente aísla el documento y lo envía a cuarentena antes de PII, pseudonimización, vinculación o salida.

## Architecture Decisions

| Decisión | Alternativas | Elección y fundamento |
|---|---|---|
| Procedencia | Guardar valores o texto fuente; reparsear sin referencias | `ReferenciaCampo` no sensible: `id_campo`, página, selector declarativo y ordinal para listas. Permite revisar la localización sin serializar PII ni dato clínico. |
| Comparación | Igualdad literal; conversión implícita | Normalizadores puros, declarados por campo: trim, colapso de espacios, coma/punto decimal, fechas a ISO y unidades canónicas. No convierten magnitud, signo, orden ni significado. |
| Extensión | `if/elif` central por tipo | `ReconciliadorDocumento` Protocol y registro `TipoDocumento → reconciliador`; cada regla conoce la representación elegida por su parser (`paginas` ECG, `paginas_ordenadas` laboratorio/eco). |
| Auditoría | Guardar texto/valor fallido | Metadatos en `ErrorDocumento`: código, campo y página; huellas HMAC de valores normalizados solo en memoria/bitácora segura si está autorizada. Cuarentena persiste exclusivamente la whitelist. |

## Data Flow

```text
Artefacto → TextoExtraido → parser Strategy → DocumentoParseado + referencias
                                             ↓
             registro de reconciliador → comparar evidencia en memoria
                                             ├─ aprobado → deteccion_pii → pseudonimizacion → salida
                                             └─ ErrorParseo(reconciliacion) → cuarentena
```

El `EjecutorPipeline._resolver_documento` inyectará `reconciliar(documento, texto)` inmediatamente después de `parsear`. Lo ejecuta mediante `_ejecutar_con_reintentos`; como el reconciliador lanza `ErrorParseo`, nunca se reintenta. Un documento rechazado no llega a `resueltos`, por lo que tampoco participa en episodios.

## File Changes

| Archivo | Acción | Descripción |
|---|---|---|
| `src/anonimizacion/reconciliacion/__init__.py` | Crear | Paquete público mínimo. |
| `src/anonimizacion/reconciliacion/base.py` | Crear | Contratos de regla, referencia y reconciliador. |
| `src/anonimizacion/reconciliacion/normalizacion.py` | Crear | Normalizadores explícitos y sin conversiones semánticas. |
| `src/anonimizacion/reconciliacion/{ecg_mortara,laboratorio_general,eco_doppler,registro}.py` | Crear | Rules/Strategies y registro por tipo. |
| `src/anonimizacion/dominio/modelos.py` | Modificar | Tipar `fuentes` como referencias no sensibles. |
| `src/anonimizacion/dominio/errores.py` | Modificar | Códigos de evidencia ausente, discrepante y ambigua; ampliar de forma opcional el metadata seguro de error. |
| `src/anonimizacion/parseo/{ecg_mortara,laboratorio_general,eco_doppler}.py` | Modificar | Emitir una referencia por header, medida, resultado, texto libre y firma que llegue al registro. |
| `src/anonimizacion/pipeline/{etapas,ejecutor}.py` | Modificar | Nueva etapa e inyección de reconciliador antes de PII. |
| `src/anonimizacion/salida/{cuarentena,modelos_orm.py}` y migración Alembic | Modificar | Persistir solo `campo`/`pagina` opcionales; nunca evidencia ni huella. |
| `tests/reconciliacion/`, `tests/{parseo,pipeline,salida}/` | Crear/Modificar | TDD unitario e integración segura. |

## Interfaces / Contracts

```python
@dataclass(frozen=True)
class ReferenciaCampo:
    id_campo: str                 # ej. ruta estable, no valor
    pagina: int                   # índice base 1
    selector: str                 # identificador de regla, no texto
    ordinal: int = 0              # filas/medidas repetidas

class ReconciliadorDocumento(Protocol):
    tipo_documento: TipoDocumento
    def reconciliar(
        self, documento: DocumentoParseado, texto: TextoExtraido
    ) -> None: ...                # ErrorParseo si no aprueba
```

Cada Strategy enumera campos requeridos y opcionales. Para un requerido, evidencia ausente, más de una coincidencia o valor distinto produce, respectivamente, `EVIDENCIA_AUSENTE`, `EVIDENCIA_AMBIGUA` o `VALOR_DISCREPANTE`, con `etapa=Etapa.RECONCILIACION`. Los opcionales solo se comparan si el parser los emitió; una referencia sin destino también falla, para impedir cobertura ficticia.

Las huellas se calculan transitoriamente como `HMAC(clave_trazabilidad, normalizado)` para diagnóstico interno; la clave se inyecta desde secreto separado, usa namespace `trazabilidad|` y no se pasa a destinos. Ninguna representación de `ReferenciaCampo`, excepción, resultado ni tabla permite llevar el valor original.

## Testing Strategy

| Capa | Qué | Enfoque strict TDD |
|---|---|---|
| Unit | Normalizadores y los tres Strategies | RED con fixtures sintéticas: igualdad, formato permitido, ausente, ambigüedad y discrepancia de valor/signo/unidad. |
| Unit | Referencias emitidas | Cada parser cubre headers, colecciones y texto que entrega; sin valores reales. |
| Integración | Ejecutor | Un aprobado llama PII; un rechazo no llama PII, claves, vínculo ni escritor y crea cuarentena con solo metadata. |
| Persistencia | Cuarentena/migración | Columnas whitelist y aserción de que no acepta texto, PII ni huella. |

## Migration / Rollout

Nueva migración aditiva para metadata segura de cuarentena. Activación obligatoria al desplegar; rollback revierte el código/configuración, sin alterar registros existentes. No hay reproceso automático.

## Open Questions

- [ ] Definir el backend operativo de `clave_trazabilidad`; debe permanecer separado de dataset y cuarentena.
- [ ] Confirmar si las huellas transitorias son necesarias en bitácora segura o se limitan a métricas agregadas.
