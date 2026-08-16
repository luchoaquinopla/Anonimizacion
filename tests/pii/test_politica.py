"""Tests de la política de PII (spec `pii-detection`): namespaces + texto libre.

Usa `SimpleNamespace` para simular el `contenido` tipado de cada parser
(`ContenidoEco.firma`, `ContenidoEco.secciones_texto`) sin importar
`anonimizacion.parseo` -- esta fase depende solo de PR1 (dominio), no de PR3
(parsers), según el Work Units table de `tasks.md`. La política usa duck
typing (`getattr`) precisamente para no acoplarse a esos tipos concretos.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.modelos import DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.pii.motor import MotorPii
from anonimizacion.pii.politica import (
    NAMESPACE_CUASI_IDENTIFICADOR,
    NAMESPACE_MEDICO,
    NAMESPACE_PACIENTE,
    clasificar,
)


@pytest.fixture(scope="module")
def motor() -> MotorPii:
    return MotorPii()


def _documento(
    *,
    identidad: IdentidadCruda,
    contenido: object = None,
    adicionales: dict[str, object] | None = None,
) -> DocumentoParseado:
    return DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=identidad,
        fecha_estudio=date(2024, 1, 1),
        contenido=contenido if contenido is not None else SimpleNamespace(),
        adicionales=adicionales or {},
    )


def test_nombre_dni_fecha_nac_van_al_namespace_paciente(motor: MotorPii) -> None:
    identidad = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        dni=SecretStr("12345678"),
        fecha_nac=SecretStr("01/01/1980"),
    )
    resultado = clasificar(_documento(identidad=identidad), motor)

    valores = {e.valor for e in resultado.elementos_paciente}
    namespaces = {e.namespace for e in resultado.elementos_paciente}
    assert valores == {"Juan Perez", "12345678", "01/01/1980"}
    assert namespaces == {NAMESPACE_PACIENTE}


def test_ids_internos_quedan_como_cuasi_identificadores(motor: MotorPii) -> None:
    identidad = IdentidadCruda(
        nombre=SecretStr("Juan Perez"),
        ids_internos=(SecretStr("PET-000123"),),
    )
    resultado = clasificar(_documento(identidad=identidad), motor)

    (elemento,) = resultado.cuasi_identificadores
    assert elemento.namespace == NAMESPACE_CUASI_IDENTIFICADOR
    assert elemento.valor == "PET-000123"


def test_medico_derivante_en_adicionales_va_a_namespace_propio(motor: MotorPii) -> None:
    identidad = IdentidadCruda(nombre=SecretStr("Juan Perez"))
    resultado = clasificar(
        _documento(identidad=identidad, adicionales={"medico_derivante": "Dr. Roberto Diaz"}),
        motor,
    )

    (elemento,) = resultado.elementos_medico
    assert elemento.namespace == NAMESPACE_MEDICO
    assert elemento.valor == "Dr. Roberto Diaz"
    # el médico nunca se mezcla con el namespace del paciente
    assert "Dr. Roberto Diaz" not in {e.valor for e in resultado.elementos_paciente}


def test_firma_del_medico_informante_va_a_namespace_medico(motor: MotorPii) -> None:
    identidad = IdentidadCruda(nombre=SecretStr("Juan Perez"))
    contenido = SimpleNamespace(firma=SimpleNamespace(nombre="Dra. Ana Lopez"))
    resultado = clasificar(_documento(identidad=identidad, contenido=contenido), motor)

    valores_medico = {e.valor for e in resultado.elementos_medico}
    assert "Dra. Ana Lopez" in valores_medico


def test_texto_libre_se_escanea_en_busca_de_pii_residual(motor: MotorPii) -> None:
    identidad = IdentidadCruda(nombre=SecretStr("Juan Perez"))
    contenido = SimpleNamespace(
        secciones_texto=(
            SimpleNamespace(texto="Se sugiere control con Dr Martin Gomez la semana proxima."),
        )
    )
    resultado = clasificar(_documento(identidad=identidad, contenido=contenido), motor)

    assert len(resultado.detecciones_texto_libre) >= 1


def test_texto_libre_ausente_no_produce_detecciones(motor: MotorPii) -> None:
    identidad = IdentidadCruda(nombre=SecretStr("Juan Perez"))
    resultado = clasificar(_documento(identidad=identidad), motor)

    assert resultado.detecciones_texto_libre == ()
