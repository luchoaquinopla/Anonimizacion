# Especificación: portal de corridas (delta)

Capacidad modificada. Extiende
`openspec/changes/operacion-segura-y-escalable/specs/portal-de-corridas/spec.md`: el requisito
"Consulta de progreso" pasa de estados agregados a embudo por etapa real, y se agregan los
requisitos de tener una implementación real del servicio y un proceso que sirva la aplicación —
hoy ninguno de los dos existe.

## Requisitos modificados

### Requisito: Consulta de progreso

El sistema **MUST** mostrar, para una corrida existente, el embudo por etapa real definido en la
capacidad `panel-de-operacion` —no estados agregados genéricos— junto con throughput y el rango
de tiempo restante, sin exponer PII.

(Antes: mostraba progreso y cuarentenas agregadas sin PII, sin especificar embudo por etapa.)

#### Escenario: Consulta

- **Given** una corrida existente
- **When** el operador la consulta
- **Then** visualiza el embudo por etapa, throughput y rango de tiempo restante, sin PII

#### Escenario: Ubicación no autorizada

- **Given** una ubicación no permitida
- **When** se solicita una corrida
- **Then** el sistema **MUST** rechazarla sin registrar PII

## Requisitos agregados

### Requisito: el servicio de corridas tiene una implementación real

El sistema **MUST** contar con una implementación real del servicio de corridas, no sólo un doble
de prueba, para que crear, consultar y reintentar corridas tenga efecto sobre datos reales.

#### Escenario: consultar una corrida real

- **Given** una corrida creada por la implementación real del servicio
- **When** se la consulta
- **Then** el estado devuelto refleja el estado real de esa corrida, no un valor fijo de prueba

### Requisito: un proceso real sirve el plano de control

El sistema **MUST** tener un punto de entrada que levante la aplicación del plano de control como
proceso real, de modo que las rutas de corridas y el panel sean alcanzables sin depender de un
test.

#### Escenario: el plano de control se levanta como proceso

- **Given** el punto de entrada del plano de control
- **When** se ejecuta fuera de un test
- **Then** el servidor queda escuchando y responde a sus rutas

### Requisito: el plano de control se levanta sin base de lectura conectada

El plano de control **MUST** poder arrancar aunque la base de lectura del embudo todavía no esté
configurada. Las rutas que dependen de ella **MUST** responder con no disponibilidad en vez de
fallar al iniciar.

#### Escenario: el embudo sin base de lectura no rompe el arranque

- **Given** el plano de control levantado sin base de lectura configurada
- **When** se solicita el embudo de una corrida
- **Then** responde con no disponibilidad, y el resto del plano de control sigue funcionando
