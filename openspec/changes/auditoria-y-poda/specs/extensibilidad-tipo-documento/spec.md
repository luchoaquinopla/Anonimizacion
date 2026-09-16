# Especificación: extensibilidad por tipo de documento

Capacidad nueva (Entrega 1). Cierra tres puntos donde agregar un 4to tipo de documento
falla en silencio hoy. Evidencia: `postgres.py:386-391`, `coordinador_episodios.py:128`,
`constructor_registro.py:231-246` (auditoria/consolidado-2026-09, obs #1338).

## Requisito 1: despacho de salida Postgres por diccionario

`salida/destinos/postgres.py` **MUST** despachar cada tipo de documento a su escritor
mediante un diccionario `{tipo: método}`, de modo que la whitelist de tipos soportados y
el despacho sean la MISMA estructura. Un tipo no presente en el diccionario **MUST**
producir `KeyError` (o excepción explícita equivalente), nunca un `else` que despache a
otro tipo.

#### Escenario: 4to tipo sin entrada de despacho falla ruidosamente
- **Given** un tipo de documento nuevo agregado a la whitelist pero sin escritor
  registrado en el diccionario de despacho
- **When** se intenta escribir un registro de ese tipo
- **Then** el sistema lanza una excepción explícita
- **And** NO escribe el registro en las tablas de otro tipo

#### Escenario: 4to tipo con entrada completa despacha correctamente
- **Given** un tipo de documento nuevo con escritor registrado en el diccionario
- **When** se escribe un registro de ese tipo
- **Then** se invoca el escritor correspondiente al tipo nuevo

## Requisito 2: conjunto de tipos requeridos inyectado

`CoordinadorEpisodios` **MUST** recibir el conjunto de tipos requeridos para completar un
episodio como parámetro de `__init__`, no como constante de módulo. La comparación contra
los tipos presentes **MUST** usar diferencia de conjuntos (`requeridos - presentes`), no
igualdad exacta de conjuntos.

#### Escenario: episodio completo con un tipo adicional no cae en cuarentena
- **Given** un `CoordinadorEpisodios` configurado con los 3 tipos requeridos actuales
- **When** llega un episodio con esos 3 tipos MÁS un 4to tipo no requerido
- **Then** el episodio se considera completo
- **And** NO se marca `ESTUDIOS_FALTANTES`

#### Escenario: episodio incompleto sigue detectándose
- **Given** el mismo coordinador
- **When** llega un episodio al que le falta uno de los 3 tipos requeridos
- **Then** se marca `ESTUDIOS_FALTANTES`

## Requisito 3: registry para construir el registro de salida

`salida/constructor_registro.py` **MUST** seleccionar el constructor de registro por tipo
de documento mediante un registry (dict), en el mismo idioma que ya usan
`parseo/registro.py:20-24` y `reconciliacion/registro.py:13-17`, no mediante una cadena
`if/elif/else raise ValueError`.

#### Escenario: 4to tipo sin constructor registrado falla explícitamente
- **Given** un tipo de documento nuevo sin entrada en el registry de constructores
- **When** se intenta construir su registro de salida
- **Then** el sistema lanza una excepción explícita nombrando el tipo faltante

#### Escenario: 4to tipo con constructor registrado construye su registro
- **Given** un tipo de documento nuevo con constructor registrado
- **When** se construye su registro de salida
- **Then** el registro se construye con el constructor correspondiente al tipo nuevo

## Requisito 4: cada arreglo se demuestra con rojo→verde sobre un 4to tipo

Cada uno de los Requisitos 1-3 **MUST** tener al menos un test que use un tipo de
documento distinto de los 3 actuales (miembro de prueba o parametrización), y que haya
fallado en el commit anterior al arreglo correspondiente.

Un test que sólo ejercite los 3 tipos de documento existentes **MUST NOT** aceptarse como
cobertura de este requisito: no puede fallar y no demuestra nada.

#### Escenario: test rechazado por no poder fallar
- **Given** un test propuesto para el Requisito 1, 2 o 3 que sólo usa ECG, laboratorio y
  eco
- **When** se revisa si ese test puede detectar el defecto original
- **Then** se rechaza, porque el defecto original sólo se manifiesta con un 4to tipo
