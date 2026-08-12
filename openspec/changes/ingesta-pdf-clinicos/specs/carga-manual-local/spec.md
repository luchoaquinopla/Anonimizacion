# Especificación: Carga manual local

## Propósito

Permitir la carga manual de lotes de PDFs de muestra desde un navegador exclusivamente local y comunicar sólo un acuse técnico seguro al finalizar el lote.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Carga múltiple exclusivamente local

La interfaz DEBE permitir arrastrar y soltar múltiples PDFs en un único lote y DEBE operar sólo de forma local, sin exposición de red. NO DEBE incorporar autenticación, API, selector de carpetas, observador de carpetas, integración hospitalaria, cola ni *broker*.

#### Escenario: Recepción de varios PDFs

- DADO un navegador ejecutado exclusivamente en el equipo local
- Y un conjunto de varios PDFs de muestra arrastrados por la persona usuaria
- CUANDO la interfaz acepta el lote
- ENTONCES DEBE contabilizar todos los archivos recibidos
- Y DEBE iniciar su tratamiento sin enviar contenido por red

#### Escenario: Origen no admitido

- DADO un intento de proporcionar documentos mediante una API, carpeta observada, sistema hospitalario o cola
- CUANDO se accede a la capacidad de carga manual
- ENTONCES el sistema NO DEBE ofrecer ni activar ese origen

### Requisito: Acuse único al completar el lote

La interfaz DEBE responder sólo después de que todos los archivos recibidos alcancen un resultado técnico terminal y sus datos transitorios hayan sido descartados. El acuse DEBE incluir únicamente las cantidades de archivos recibidos y procesados y un código técnico seguro por archivo.

#### Escenario: Lote aún en curso

- DADO un lote con al menos un archivo cuyo tratamiento no ha terminado
- CUANDO la interfaz evalúa si debe presentar el resultado
- ENTONCES NO DEBE presentar acuses parciales ni resultados por archivo

#### Escenario: Lote completado

- DADO un lote en el que cada archivo alcanzó un resultado técnico terminal
- Y los datos transitorios de cada archivo ya fueron descartados
- CUANDO la interfaz presenta el acuse
- ENTONCES DEBE mostrar un único acuse con las cantidades recibida y procesada
- Y DEBE incluir exactamente un código técnico seguro por archivo

#### Escenario: Resultado técnico de rechazo

- DADO un archivo que no puede superar un control obligatorio
- CUANDO el sistema completa su tratamiento controlado y descarta sus datos
- ENTONCES DEBE contabilizarlo como procesado con un código técnico seguro de resultado no satisfactorio
- Y NO DEBE revelar el dato, regla ni diagnóstico detallado que originó el resultado

### Requisito: Minimización estricta de la interfaz

La interfaz NO DEBE mostrar nombres de PDF, texto extraído, PII/PHI, valores clínicos originales o anonimizados, observaciones, *features*, diagnósticos ni diagnósticos técnicos detallados. Los códigos por archivo DEBEN pertenecer a un conjunto seguro y no identificante y NO DEBEN codificar contenido del documento.

#### Escenario: Composición de un acuse

- DADO que el procesamiento produjo datos clínicos transitorios o detalles internos de validación
- CUANDO se compone la respuesta del lote
- ENTONCES el sistema DEBE excluir esos datos y detalles
- Y DEBE limitar la respuesta a los contadores y códigos técnicos permitidos

#### Escenario: Nombre disponible en el navegador

- DADO que el navegador conoce el nombre local de un PDF cargado
- CUANDO presenta el lote o su acuse
- ENTONCES la interfaz NO DEBE mostrar ni devolver ese nombre
