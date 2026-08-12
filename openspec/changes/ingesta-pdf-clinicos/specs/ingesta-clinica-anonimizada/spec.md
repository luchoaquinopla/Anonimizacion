# Especificación: Ingesta clínica anonimizada

## Propósito

Procesar cada PDF clínico como dato efímero mediante un caso de uso desacoplado del origen, sin exponer ni conservar contenido clínico o identificante.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Puerto de entrada independiente del origen

El sistema DEBE ofrecer un puerto de entrada para invocar el caso de uso de ingesta con el contenido transitorio de un PDF. El contrato DEBE mantener la extracción, la privacidad y el dominio independientes del adaptador de origen, y NO DEBE seleccionar ni exigir un protocolo, *framework* o mecanismo para fuentes futuras.

#### Escenario: Invocación desde la carga manual

- DADO un PDF recibido por el adaptador local de carga manual
- CUANDO el adaptador solicita su ingesta
- ENTONCES DEBE invocar el caso de uso mediante el puerto de entrada
- Y la extracción, la privacidad y las reglas de dominio NO DEBEN depender de la interfaz de navegador

#### Escenario: Sustitución conceptual del origen

- DADO un futuro adaptador autorizado que entregue el mismo contenido transitorio admitido
- CUANDO invoque el puerto de entrada
- ENTONCES el caso de uso DEBE conservar las mismas reglas de extracción, privacidad, calidad y descarte
- Y el puerto NO DEBE imponer qué fuente o transporte utiliza ese adaptador

### Requisito: Procesamiento síncrono y exclusivamente en memoria

El caso de uso DEBE completar de forma síncrona, para cada PDF, la clasificación, extracción por familia, anonimización, validación residual y controles de calidad aplicables. Todo PDF, texto, PII/PHI, dato clínico original o anonimizado, observación, resultado detallado y dato intermedio DEBE permanecer sólo en memoria y DEBE descartarse antes de completar el tratamiento del archivo, tanto en éxito como en error.

#### Escenario: Archivo tratado satisfactoriamente

- DADO un PDF clínico admitido
- CUANDO completa todos los controles obligatorios
- ENTONCES el caso de uso DEBE descartar sus entradas y salidas clínicas transitorias antes de completar
- Y DEBE devolver al adaptador sólo un resultado técnico seguro no identificante

#### Escenario: Error durante el tratamiento

- DADO un PDF cuyo tratamiento genera un error o rechazo
- CUANDO el caso de uso alcanza un resultado terminal controlado
- ENTONCES DEBE descartar igualmente el PDF y todos los datos transitorios
- Y NO DEBE devolver contenido, valores ni diagnósticos detallados

### Requisito: Ausencia de retención y canales laterales

El sistema NO DEBE persistir PDFs, texto extraído, PII/PHI, datos clínicos originales o anonimizados, observaciones, resultados, temporales ni estados intermedios. Tampoco DEBE incluir contenido documental o clínico en registros, mensajes o cargas de cola.

#### Escenario: Intento de escritura sensible

- DADO cualquier etapa del caso de uso
- CUANDO se intenta escribir contenido o un resultado clínico en almacenamiento, archivo temporal o registro
- ENTONCES el sistema DEBE impedir la escritura
- Y DEBE completar el descarte en memoria

#### Escenario: Infraestructura de entrega ausente

- DADO el procesamiento de un lote local
- CUANDO se ejecuta el caso de uso
- ENTONCES NO DEBE requerir base de datos, cola, *broker* ni servicio de red
