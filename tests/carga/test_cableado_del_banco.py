"""El banco de carga debe armar el pipeline como lo arma producción.

Ésta es la tercera vez que la divergencia entre ambos cableados produce un
problema, así que queda fijada como contrato:

1. El banco inyectaba el coordinador de episodios y producción no, de modo que
   los conteos de cuarentena que el proyecto registraba como evidencia describían
   un camino que el trabajador no recorría.
2. El invariante de idempotencia a escala no pudo verificarse en el banco porque
   usa un destino en memoria y nunca escribe en SQL.

El riesgo no es que el banco use dobles —eso es legítimo y necesario: con el
motor de PII real cada ensayo tardaría horas—. El riesgo es que el banco arme el
ejecutor A MANO, porque entonces cualquier cableado nuevo que se agregue a la
raíz de composición de producción no llega al banco, y nadie se entera.

La solución no es prohibir los dobles: es que el banco pase por la MISMA fábrica
y sobrescriba explícitamente sólo lo que necesita.
"""
from __future__ import annotations

import inspect


def test_el_banco_arma_el_pipeline_por_la_fabrica_de_produccion() -> None:
    from tests.fixtures import corpus_piloto

    fuente = inspect.getsource(corpus_piloto)
    assert "construir_fabrica_ejecutor" in fuente, (
        "el banco de carga volvio a armar EjecutorPipeline a mano: cualquier "
        "cableado nuevo de produccion dejaria de llegar al banco en silencio"
    )
    assert "EjecutorPipeline(" not in fuente, (
        "el banco instancia EjecutorPipeline directamente en vez de pasar por "
        "la fabrica"
    )


def test_la_fabrica_expone_los_puntos_de_inyeccion_que_el_banco_necesita() -> None:
    """`dormir` y `resolver_claves` no son parches de test: son puntos de
    inyección legítimos de la raíz de composición, con valores de producción por
    defecto. Exponerlos es lo que permite que el banco use la fábrica en vez de
    duplicarla."""
    from anonimizacion.trabajadores.tareas import construir_fabrica_ejecutor

    parametros = inspect.signature(construir_fabrica_ejecutor).parameters
    assert "dormir" in parametros
    assert "resolver_claves" in parametros
    assert parametros["dormir"].default is None
    assert parametros["resolver_claves"].default is None
