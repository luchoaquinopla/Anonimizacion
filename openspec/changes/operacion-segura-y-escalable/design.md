# Diseño: operación segura y escalable

## Contexto

El pipeline actual debe evolucionar desde una ejecución local orientada a documentos hacia una operación institucional que procese miles de PDFs. La unidad de publicación no es un PDF: es un episodio clínico formado por los estudios que pueden asociarse con certeza. El navegador no debe transportar, procesar ni conservar los PDFs.

Se mantienen estas restricciones: operación totalmente interna, sin servicios externos para PII; originales separados y cifrados; reconciliación como compuerta obligatoria antes de anonimizar y publicar; y cuarentena ante incertidumbre. La cinecoronariografía no forma parte de este cambio.

## Objetivos y no objetivos

### Objetivos

- Permitir que personal institucional inicie y consulte corridas desde una web interna, seleccionando una ruta ya disponible en el servidor.
- Hacer durable, reanudable e idempotente el procesamiento de miles de PDFs.
- Paralelizar el trabajo por archivo sin perder la decisión posterior por paciente/episodio.
- Publicar sólo bundles pseudónimos y proyecciones Parquet, nunca PDFs crudos.
- Crear un corpus local y reproducible de PDFs sintéticos con resultado esperado conocido.
- Convertir el fallo de ecocardiograma en un caso reproducible sin exponer PII ni resultados clínicos.

### No objetivos

- Portal público, carga masiva desde el navegador, Kubernetes, ni modelos clínicos.
- Aceptar documentos no reconciliados para aumentar cobertura.
- Implementar cinecoronariografía antes de contar con muestra y contrato de extracción.

## Decisiones de arquitectura

### 1. Portal como plano de control, no como canal de archivos

La aplicación web interna ofrece: crear corrida, seleccionar una ruta autorizada, consultar progreso, reintentar documentos permitidos y descargar reportes sin PII. La ruta seleccionada debe pertenecer a una lista de raíces configuradas por IT. La API guarda sólo el identificador de corrida y metadata operacional; no recibe contenido PDF ni secretos del navegador.

**Alternativas evaluadas**

| Alternativa | Resultado | Motivo |
|---|---|---|
| Subir miles de PDFs por web | Descartada | aumenta superficie de exposición, límites de transferencia y complejidad de reintentos. |
| Ejecutable Windows por operador | Compatible como futura envoltura | facilita una estación aislada, pero complica actualizaciones y no resuelve coordinación multiworker. |
| Servicio de carpetas sin web | Compatible como entrada adicional | es el camino operativo más simple, pero no da visibilidad de corridas. |
| Web interna + rutas autorizadas | Elegida | separa experiencia del usuario y procesamiento; permite auditoría y escala. |

La entrega recomendada es un instalador/servicio administrado por IT (Windows Service o servicio Linux), con portal en intranet. Docker puede existir como detalle de instalación para IT, pero jamás es un requisito ni una interfaz del médico.

### 2. Corrida durable y estados en PostgreSQL

Una `corrida` es la unidad administrativa. Al iniciarla, el servicio de ingesta recorre la carpeta, calcula una huella criptográfica del archivo, registra su ruta autorizada y crea una fila `documento_corrida`. La base de datos es la fuente de verdad para estados y reintentos.

Estados propuestos:

```text
CREADA -> INVENTARIANDO -> PROCESANDO -> RECONCILIANDO -> PUBLICANDO -> COMPLETADA
                         -> COMPLETADA_CON_CUARENTENA
                         -> FALLIDA
```

Por documento:

```text
INVENTARIADO -> CLASIFICADO -> EXTRAIDO_MINIMO -> ASOCIADO -> EXTRAIDO_COMPLETO
             -> RECONCILIADO -> APROBADO | CUARENTENA | ERROR_RECUPERABLE | ERROR_FINAL
```

Transiciones se realizan en transacciones y se condicionan por versión/estado esperado. La clave de idempotencia es `(corrida_id, huella_contenido)`; publicar un episodio también usa `(id_paciente, id_episodio, version_pipeline)`.

### 3. Paralelismo por documento con coordinación posterior por episodio

Los workers pueden clasificar y extraer distintos PDFs independientemente. Cada worker sólo persiste resultados intermedios protegidos y un evento de estado. Un coordinador durable consulta documentos listos, crea candidatos por `id_paciente` pseudónimo y aplica las ventanas clínicas configuradas para formar `episodio`.

El coordinador no publica al encontrar el primer archivo: espera la condición de cierre de la corrida o de estabilidad configurada. Para cada candidato arma un expediente con ECG, laboratorio y ecocardiograma; los faltantes, empates o asociaciones ambiguas pasan a cuarentena. Así se evita que una tarea aislada por PDF decida incorrectamente el paquete final.

### 4. Orden seguro de transformación

```text
inventario -> clasificación/extracción mínima -> pseudónimo transitorio
-> asociación por paciente y fecha -> extracción completa -> reconciliación
-> remoción de PII -> publicación de bundle y Parquet
```

La reconciliación compara el PDF de origen con la extracción estructurada y valida presencia, consistencia y asociación. Si falla, no se anonimiza ni publica. El pseudónimo transitorio se genera dentro del servidor con HMAC y un secreto administrado fuera de la base de datos/dataset; su entrada identificatoria se elimina al finalizar la etapa necesaria.

### 5. Salida por carpetas como proyección, no como base de coordinación

La base de datos coordina y audita. El almacenamiento final es una proyección idempotente:

```text
dataset_anonimizado/
  {id_paciente}/
    {id_episodio}/
      manifest.json
      ecg.json
      laboratorio.parquet
      ecocardiograma.json
```

`manifest.json` contiene versión de esquema, versión del pipeline, huellas no reversibles, estado de completitud y referencias lógicas; no PII ni rutas de originales. En paralelo se genera una proyección analítica Parquet, una fila por episodio, para alimentar modelos sin recorrer directorios. Los originales y la cuarentena se almacenan cifrados, fuera de `dataset_anonimizado/`, con permisos y retención independientes.

### 6. Contratos internos

Contratos a introducir o estabilizar:

| Contrato | Responsabilidad |
|---|---|
| `ServicioCorridas` | crear, cancelar, consultar y reanudar una corrida. |
| `InventariadorDocumentos` | recorrer raíz autorizada, validar extensión/tamaño y producir inventario idempotente. |
| `TrabajadorDocumento` | clasificar, extraer mínimo/completo y escribir resultado/estado, sin publicar. |
| `CoordinadorEpisodios` | resolver candidatos, ventanas y completitud; pedir reconciliación. |
| `ReconciliadorDocumento` | aprobar o devolver razones estructuradas de cuarentena. |
| `PublicadorBundles` | materializar carpeta segura y Parquet de episodios aprobados de forma atómica. |
| `RegistroDiagnosticoSeguro` | emitir códigos, versión de parser y huellas; nunca texto clínico, PII o valores. |

Los DTOs y nombres concretos usarán las convenciones españolas ya vigentes. Los contratos deben poder ejecutarse en proceso durante pruebas y detrás de una cola para producción; esto evita que Celery sea la fuente de verdad del flujo.

### 7. Diagnóstico de ecocardiograma sin PII

No se modificará el parser por conjetura. Al entrar en cuarentena se registrará un evento seguro con: `codigo_motivo`, etapa, tipo detectado, versión del parser, versión de plantilla, número de página, presencia/ausencia de etiquetas esperadas, estructura de bloques y huella de archivo. Se prohíbe registrar nombre, DNI, fechas, texto libre, medidas o fragmentos del PDF.

El diagnóstico debe permitir seleccionar una fixture sintética equivalente. La corrección se implementará primero como prueba que reproduce el código de cuarentena y sólo después como cambio de parser. Mientras no haya evidencia, la cuarentena se conserva.

### 8. Corpus sintético local

Se recrearán plantillas programáticas de ECG, laboratorio y eco usando posiciones/tablas equivalentes a las muestras observadas localmente. No se editarán, redistribuirán ni incluirán PDFs reales en el repositorio. Un generador con semilla produce tanto PDFs como un oráculo estructurado por corrida.

El corpus cubre: episodios completos, faltantes, duplicados, fechas limítrofes, asociaciones ambiguas, documentos corruptos, PII en texto libre y variaciones de paginación/plantilla. Las pruebas comparan extracción, decisión de reconciliación, ausencia de PII y contenido de bundle contra el oráculo. Las pruebas de carga miden tasa, reintentos, memoria y duplicación de salida para escalones de 1k, 10k y 100k documentos, sin exigir que CI ejecute el máximo escalón.

## Componentes y archivos esperados

Los nombres finales deberán ajustarse a la estructura real del repositorio, conservando las responsabilidades:

| Área | Archivos/componentes esperados |
|---|---|
| Dominio de corridas | `src/anonimizacion/dominio/corridas.py`, `.../episodios.py`, `.../estados.py` |
| Aplicación | `src/anonimizacion/aplicacion/servicio_corridas.py`, `.../coordinador_episodios.py` |
| Adaptadores | `src/anonimizacion/infraestructura/repositorios_postgres.py`, `.../cola_trabajos.py`, `.../almacenamiento.py` |
| Interfaz | `src/anonimizacion/web/` y rutas de estado de corrida |
| Salida | `src/anonimizacion/salida/publicador_bundles.py`, `.../proyeccion_parquet.py` |
| Sintéticos | `tests/fabricas_pdf/` y `tests/corpus_sintetico/` |
| Diagnóstico | `src/anonimizacion/observabilidad/diagnostico_seguro.py` |
| Despliegue | `deploy/` con configuración de servicio, variables de entorno documentadas y guía de operación interna |

Antes de crear archivos se mapearán los módulos actuales; no se duplicarán abstracciones existentes.

## Seguridad y operación

- Cuentas de servicio con mínimo privilegio: lectura en entrada, escritura en salida/cuarentena, sin acceso del portal a secretos.
- TLS y autenticación institucional para la intranet; autorización por rol para iniciar/consultar/reintentar.
- Secretos en el almacén institucional o variables protegidas de servicio, nunca en repositorio, PostgreSQL, manifiestos ni logs.
- Cifrado en reposo para originales y cuarentena; copias de seguridad comprobadas y retención definida por la institución.
- Métricas agregadas por corrida: conteos, duración, códigos de cuarentena y versiones; prohibido exportar contenido clínico o PII.
- Límite de concurrencia y backpressure configurables para proteger CPU, RAM, PostgreSQL y almacenamiento.

## Estrategia de entrega y rollback

El cambio debe dividirse por límites autónomos si la estimación excede el presupuesto de revisión: (1) dominio y persistencia de corridas, (2) ingesta/workers/coordinación, (3) publicación y portal, (4) corpus/carga y eco. Cada corte debe incluir migraciones, pruebas y reversión.

Rollback: deshabilitar nuevas corridas, esperar o detener trabajos seguros, conservar estado/auditoría y cuarentena, y desactivar la proyección nueva. Los bundles se escriben en directorio temporal y se renombran atómicamente sólo tras validación; las salidas ya aprobadas no se sobrescriben sin una nueva versión explícita.

## Validación

1. Pruebas unitarias de transiciones, idempotencia, ventana y asociaciones ambiguas.
2. Pruebas de integración contra PostgreSQL/cola y almacenamiento temporal: caída/reinicio no duplica episodios.
3. Corpus sintético con oráculo: ninguna salida incluye PII y cada decisión coincide con el caso esperado.
4. Prueba focalizada de eco basada en metadata segura y fixture sintética reproducible.
5. Pruebas de carga por escalones y presupuesto de recursos acordado con infraestructura.
6. Revisión manual de permisos, cifrado, secretos y reportes antes de usar una corrida institucional.

## Riesgos abiertos

- La ventana clínica exacta y el criterio de cierre de episodio requieren validación clínica.
- La infraestructura institucional debe definir ubicación, backups, retención, autenticación y gestor de secretos.
- Sin un código de cuarentena o una fixture equivalente, el parser de eco no debe cambiarse.
- La capacidad real depende de medición con hardware representativo; no se debe afirmar soporte de 100k sin prueba de carga.
