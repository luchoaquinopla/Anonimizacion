# Especificación: Validación de privacidad y calidad

## Propósito

Impedir que un archivo se considere procesado sin completar controles independientes de privacidad y controles de calidad y completitud, manteniendo efímeros todos los hallazgos.

En esta especificación, DEBE corresponde a MUST (obligatorio) y NO DEBE corresponde a MUST NOT (prohibido) según RFC 2119.

## Requisitos

### Requisito: Controles obligatorios antes del resultado

Para cada archivo, el sistema DEBE ejecutar anonimización, validación residual de PII/PHI independiente de la anonimización y validación de calidad y completitud antes de emitir su resultado técnico. Si un control no puede ejecutarse o completarse, el archivo DEBE obtener un resultado técnico no satisfactorio.

#### Escenario: Controles superados

- DADO un archivo cuya extracción aplicable terminó
- CUANDO la anonimización, la validación residual independiente y los controles de calidad y completitud concluyen satisfactoriamente
- ENTONCES el sistema DEBE permitir un resultado técnico satisfactorio
- Y DEBE descartar los datos y hallazgos transitorios antes de completar el archivo

#### Escenario: Control incompleto

- DADO un archivo para el cual un control obligatorio no puede completarse
- CUANDO se determina su resultado
- ENTONCES el sistema DEBE producir un código técnico seguro no satisfactorio
- Y NO DEBE tratar la ausencia del control como aprobación

### Requisito: Bloqueo por privacidad o calidad

El sistema DEBE impedir un resultado satisfactorio cuando detecte PII/PHI residual, campos requeridos no verificables o incumplimiento de la política de calidad y completitud. Los detalles del hallazgo NO DEBEN cruzar el límite del caso de uso ni aparecer en la UI.

#### Escenario: PII o PHI residual

- DADO que la validación residual independiente detecta PII o PHI
- CUANDO se decide el resultado del archivo
- ENTONCES el sistema DEBE bloquear el resultado satisfactorio
- Y DEBE devolver únicamente un código técnico seguro no identificante

#### Escenario: Calidad insuficiente

- DADO un campo requerido faltante, ambiguo, malformado o truncado según la política aprobada
- CUANDO se evalúa la completitud del archivo
- ENTONCES el sistema DEBE bloquear el resultado satisfactorio
- Y NO DEBE incluir el nombre del campo, su valor ni el detalle de la regla en la respuesta

### Requisito: Hallazgos efímeros

Los hallazgos, valores, versiones intermedias y diagnósticos de privacidad o calidad DEBEN existir sólo en memoria durante el tratamiento del archivo y NO DEBEN persistirse ni registrarse con contenido.

#### Escenario: Fin del archivo rechazado

- DADO un archivo rechazado por privacidad o calidad
- CUANDO termina su tratamiento
- ENTONCES el sistema DEBE descartar todos los hallazgos y datos asociados
- Y sólo el código técnico seguro PUEDE (MAY: permitido) permanecer lo necesario para componer el acuse del lote
