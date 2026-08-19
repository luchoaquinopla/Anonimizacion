"""Tests de modelos de dominio. PII siempre sintética — ver AGENTS.md."""

from __future__ import annotations

from datetime import date

import pytest

from anonimizacion.dominio.modelos import (
    ClavesPaciente,
    DocumentoParseado,
    IdentidadCruda,
    RegistroAnonimizado,
)
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.reconciliacion.base import ReferenciaCampo

NOMBRE_FICTICIO = "Juana Pérez de Prueba"
DNI_FICTICIO = "11222333"


def test_identidad_cruda_redacta_en_repr() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO, dni=DNI_FICTICIO)
    texto = repr(identidad)
    assert NOMBRE_FICTICIO not in texto
    assert DNI_FICTICIO not in texto
    assert texto == "IdentidadCruda(**redactado**)"


def test_identidad_cruda_redacta_en_str() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO, dni=DNI_FICTICIO)
    assert str(identidad) == "IdentidadCruda(**redactado**)"


def test_identidad_cruda_expone_valor_solo_via_get_secret_value() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO)
    assert identidad.nombre.get_secret_value() == NOMBRE_FICTICIO


def test_identidad_cruda_dni_y_fecha_nac_son_opcionales_ecg_no_trae_dni() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO)
    assert identidad.dni is None
    assert identidad.fecha_nac is None


def test_identidad_cruda_es_inmutable() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO)
    with pytest.raises(Exception):
        identidad.nombre = "otro"  # type: ignore[misc]


def test_documento_parseado_agrupa_tipo_identidad_y_fuentes() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO, dni=DNI_FICTICIO)
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=identidad,
        fecha_estudio=date(2024, 1, 15),
        contenido={"seccion": "HEMATOLOGIA"},
    )
    assert documento.tipo_documento == TipoDocumento.LABORATORIO
    assert documento.adicionales == {}
    assert documento.fuentes == ()


def test_documento_parseado_conserva_solo_referencias_de_fuente() -> None:
    referencia = ReferenciaCampo(id_campo="ecg.vent_rate", pagina=1, selector="ecg.vent_rate")
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=NOMBRE_FICTICIO),
        fecha_estudio=date(2024, 1, 15),
        contenido={},
        fuentes=(referencia,),
    )
    assert documento.fuentes == (referencia,)


def test_documento_parseado_rechaza_fuentes_que_no_son_referencias() -> None:
    with pytest.raises(TypeError):
        DocumentoParseado(
            tipo_documento=TipoDocumento.ECG,
            version_esquema=1,
            identidad=IdentidadCruda(nombre=NOMBRE_FICTICIO),
            fecha_estudio=date(2024, 1, 15),
            contenido={},
            fuentes=("ecg.vent_rate",),  # type: ignore[arg-type]
        )


def test_identidad_cruda_ids_internos_no_se_puede_mutar_por_contenido() -> None:
    identidad = IdentidadCruda(nombre=NOMBRE_FICTICIO, ids_internos=("id-1",))
    with pytest.raises(AttributeError):
        identidad.ids_internos.append("id-2")  # type: ignore[attr-defined]


def test_documento_parseado_adicionales_no_se_puede_mutar_por_contenido() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=NOMBRE_FICTICIO),
        fecha_estudio=date(2024, 1, 15),
        contenido={"seccion": "HEMATOLOGIA"},
    )
    with pytest.raises(TypeError):
        documento.adicionales["x"] = "y"  # type: ignore[index]


def test_claves_paciente_sin_clave_resoluble_queda_en_none() -> None:
    claves = ClavesPaciente(id_paciente=None, id_alt_paciente=None, version_clave=1)
    assert claves.id_paciente is None
    assert claves.id_alt_paciente is None


def test_registro_anonimizado_no_tiene_campos_de_pii() -> None:
    registro = RegistroAnonimizado(
        id_paciente="a1b2c3d4e5f6",
        id_episodio="f6e5d4c3b2a1",
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        fecha_estudio=date(2024, 1, 15),
        contenido={"vent_rate": 72},
    )
    campos = vars(registro)
    assert "nombre" not in campos
    assert "dni" not in campos
    assert "fecha_nac" not in campos
