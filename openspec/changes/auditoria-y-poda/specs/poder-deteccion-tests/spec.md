# Especificación: poder de detección de los tests

Capacidad nueva (Entrega 3). Recupera capacidad de atrapar bugs perdida en tests
existentes: un espejo tautológico, 31 tests sin oráculo y un gap de cobertura sobre
códigos de cuarentena. Evidencia: `auditoria/consolidado-2026-09` (obs #1338),
`proposal.md` sección "Entrega 3".

## Requisito 1: `reconciliar(...)` se verifica sobre su valor de retorno

Los tests de `tests/reconciliacion/` que llaman `reconciliar(...)` **MUST** afirmar sobre
el conjunto de campos no extraídos que esa función devuelve. Un `assert resultado is not
None` (o la ausencia total de `assert`/`pytest.raises`, como en
`test_ecg_mortara.py:57` y `:77`) **MUST NOT** aceptarse como cobertura de este
requisito.

#### Escenario: degradación silenciosa detectada
- **Given** una entrada cuyo parser hoy extrae correctamente un campo, y una versión
  modificada que deja de extraerlo sin lanzar excepción
- **When** se corre el test de reconciliación correspondiente
- **Then** el test falla, porque el campo faltante aparece en el conjunto de retorno y el
  test lo verifica explícitamente

#### Escenario: extracción completa sigue aprobando
- **Given** una entrada cuyo parser extrae todos los campos esperados
- **When** se corre el test de reconciliación
- **Then** el conjunto de campos no extraídos es vacío y el test lo verifica

## Requisito 2: exhaustividad `CodigoErrorDocumento` → `EXPLICACION_POR_CODIGO`

El sistema **MUST** tener un test que falle si existe algún miembro de
`CodigoErrorDocumento` sin entrada correspondiente en
`web/codigos_cuarentena.py::EXPLICACION_POR_CODIGO`.

#### Escenario: código nuevo sin explicación falla el test
- **Given** un nuevo miembro agregado a `CodigoErrorDocumento` sin entrada en
  `EXPLICACION_POR_CODIGO`
- **When** se corre el test de exhaustividad
- **Then** el test falla, señalando el código sin explicación

#### Escenario: todos los códigos actuales tienen explicación
- **Given** el estado actual de `CodigoErrorDocumento` y `EXPLICACION_POR_CODIGO`
- **When** se corre el test de exhaustividad
- **Then** el test pasa

## Requisito 3: el test espejo tautológico se resuelve

`tests/pipeline/test_equivalencia_agrupacion.py:51-104` compara
`_episodios_del_coordinador(x)` contra `vincular_episodios(x)`, pero
`coordinador_episodios.py:86-103` delega en `vincular_episodios` — es `f(x) == g(x)`
donde `f` llama a `g`, y no puede fallar nunca.

El sistema **MUST** reemplazar ese test por uno con oráculo independiente (fechas y
agrupaciones esperadas escritas a mano) **O** eliminarlo con una justificación escrita en
el PR de la Entrega 3. En cualquiera de los dos casos, el docstring de producción
`coordinador_episodios.py:9-13` **MUST** dejar de afirmar que ese test "fija esa
equivalencia como contrato".

#### Escenario: test reemplazado detecta una regresión de agrupación
- **Given** el test con oráculo independiente (agrupaciones esperadas escritas a mano)
- **When** se rompe a propósito la lógica de agrupación por fecha ancla
- **Then** el test falla

#### Escenario: docstring corregido
- **Given** el docstring actual de `coordinador_episodios.py:9-13`
- **When** se resuelve el Requisito 3 (reemplazo o eliminación del test espejo)
- **Then** el docstring ya no afirma que un test tautológico fija el contrato de
  equivalencia
