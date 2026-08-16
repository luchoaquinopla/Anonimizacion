"""Tests del contrato `ParseadorDocumento` (spec: document-parsing).

Es un Protocol runtime-checkable: cualquier objeto con `tipo_documento` +
`parsear(texto)` conforma, sin necesidad de heredar de una clase base.
"""

from __future__ import annotations

from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.base import ParseadorDocumento


def test_objeto_con_forma_correcta_conforma_al_protocol() -> None:
    class ParseadorFalso:
        tipo_documento = TipoDocumento.LABORATORIO

        def parsear(self, texto):  # noqa: ANN001, ANN201 - firma mínima de prueba
            ...

    assert isinstance(ParseadorFalso(), ParseadorDocumento)


def test_objeto_sin_metodo_parsear_no_conforma() -> None:
    class NoParseador:
        tipo_documento = TipoDocumento.LABORATORIO

    assert not isinstance(NoParseador(), ParseadorDocumento)
