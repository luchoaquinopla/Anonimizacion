"""Tests de `salida/constructor_registro.py` (tasks.md 7.2, spec `anonymized-output`).

`construir_registro` es el ensamblaje final: `DocumentoParseado` +
`ClavesPaciente` (+ `id_episodio` ya resuelto por `vinculacion.py`, + el
`pepper` para poder pseudonimizar al médico en namespace propio, Q3) ->
`RegistroAnonimizado`. Estos tests verifican, por tipo de documento, que:

1. Cero PII de identidad del paciente llega al registro (eso ya no viaja en
   `contenido`/`adicionales` de `DocumentoParseado`, así que basta con
   confirmar que el registro no reintroduce nada de `documento.identidad`).
2. El nombre/matrícula del médico se reemplazan por sus HMAC (`id_medico`,
   `id_matricula_informante`), nunca el texto crudo.
3. `contenido` queda tipado según `modelos_salida.py`, coherente con el
   `tipo_documento`.
"""

from __future__ import annotations

from datetime import date, time

import pytest
from pydantic import SecretStr

from anonimizacion.dominio.modelos import ClavesPaciente, DocumentoParseado, IdentidadCruda
from anonimizacion.dominio.precision_hora import PrecisionHora
from anonimizacion.dominio.tipos_documento import TipoDocumento
from anonimizacion.parseo.ecg_mortara import ContenidoEcg
from anonimizacion.parseo.eco_doppler import ContenidoEco, FirmaMedico, MedidaEco, SeccionTextoEco
from anonimizacion.parseo.laboratorio_general import ContenidoLaboratorio, ResultadoLaboratorio
from anonimizacion.pseudonimizacion.claves import generar_id_matricula_medico, generar_id_medico
from anonimizacion.salida.constructor_registro import construir_registro
from anonimizacion.salida.modelos_salida import ContenidoEcgSalida, ContenidoEcoSalida, ContenidoLaboratorioSalida

PEPPER_TEST = b"pepper-fijo-de-test-nunca-real"
CLAVES_TEST = ClavesPaciente(id_paciente="pid-abc123", id_alt_paciente=None, version_clave=1)
ID_EPISODIO_TEST = "episodio-xyz789"


def test_laboratorio_pseudonimiza_medico_y_arma_contenido_eav() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.LABORATORIO,
        version_esquema=1,
        identidad=IdentidadCruda(
            nombre=SecretStr("Juan Perez"), dni=SecretStr("12345678"), fecha_nac=SecretStr("1980-01-01")
        ),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoLaboratorio(
            numero_peticion="P-1",
            resultados=(
                ResultadoLaboratorio(
                    seccion="HEMATOLOGIA",
                    prueba="Hemoglobina",
                    resultado="14.5",
                    unidades="g/dL",
                    valores_referencia="12-16",
                ),
                ResultadoLaboratorio(
                    seccion="QUIMICA CLINICA",
                    prueba="Grupo sanguineo",
                    resultado="O+",
                    unidades=None,
                    valores_referencia=None,
                ),
            ),
        ),
        adicionales={"medico_derivante": "Dr. Roberto Diaz", "origen": "Guardia"},
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert registro.id_paciente == "pid-abc123"
    assert registro.id_episodio == ID_EPISODIO_TEST
    assert registro.tipo_documento is TipoDocumento.LABORATORIO
    assert registro.fecha_estudio == date(2024, 1, 10)

    assert isinstance(registro.contenido, ContenidoLaboratorioSalida)
    assert registro.contenido.id_medico == generar_id_medico(PEPPER_TEST, "Dr. Roberto Diaz")
    assert len(registro.contenido.resultados) == 2

    fila_numerica = registro.contenido.resultados[0]
    assert fila_numerica.analito == "Hemoglobina"
    assert fila_numerica.seccion == "HEMATOLOGIA"
    assert fila_numerica.valor_num == 14.5
    assert fila_numerica.valor_texto is None
    assert fila_numerica.unidad == "g/dL"
    assert fila_numerica.ref_min == 12.0
    assert fila_numerica.ref_max == 16.0

    fila_texto = registro.contenido.resultados[1]
    assert fila_texto.valor_num is None
    assert fila_texto.valor_texto == "O+"
    assert fila_texto.ref_min is None
    assert fila_texto.ref_max is None

    # nunca el nombre crudo del médico, ni en adicionales
    assert "medico_derivante" not in registro.adicionales
    assert "Dr. Roberto Diaz" not in str(registro.adicionales)
    assert "Dr. Roberto Diaz" not in str(registro.contenido)
    assert registro.adicionales["origen"] == "Guardia"


def test_ecg_pseudonimiza_medico_y_arma_contenido_ancho() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEcg(
            vent_rate="72",
            pr_interval="160",
            qrs_duration="90",
            qt_qtc="400/420",
            ejes="P60 R30 T40",
        ),
        adicionales={
            "medico_derivante": "Dr. Ana Lopez",
            "tecnico": "Operador Sintetico",
            "institucion": "Clinica Central",
            "advertencia_equipo": "PID_NAME_MISMATCH",
        },
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert isinstance(registro.contenido, ContenidoEcgSalida)
    assert registro.contenido.id_medico == generar_id_medico(PEPPER_TEST, "Dr. Ana Lopez")
    assert registro.contenido.vent_rate == "72"
    assert registro.contenido.qrs_duration == "90"

    assert "medico_derivante" not in registro.adicionales
    assert "Dr. Ana Lopez" not in str(registro.adicionales)
    assert "Operador Sintetico" not in str(registro.adicionales)
    assert registro.adicionales["institucion"] == "Clinica Central"
    assert registro.adicionales["advertencia_equipo"] == "PID_NAME_MISMATCH"


def test_eco_pseudonimiza_medico_solicitante_e_informante_y_matricula() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez"), dni=SecretStr("12345678")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(
            medidas=(
                MedidaEco(nombre="AO", valor="28", unidad="mm"),
                MedidaEco(nombre="P. Posterior", valor="9", unidad="mm"),
                MedidaEco(nombre="Medida rara no tabulada", valor="1", unidad=None),
            ),
            secciones_texto=(SeccionTextoEco(nombre="CONCLUSIONES", texto="Funcion sistolica conservada"),),
            firma=FirmaMedico(nombre="Dr. Carlos Gomez", matricula="MP12345"),
        ),
        adicionales={"medico_solicitante": "Dr. Ana Lopez", "peso": "70"},
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert isinstance(registro.contenido, ContenidoEcoSalida)
    assert registro.contenido.id_medico_solicitante == generar_id_medico(PEPPER_TEST, "Dr. Ana Lopez")
    assert registro.contenido.id_medico_informante == generar_id_medico(PEPPER_TEST, "Dr. Carlos Gomez")
    assert registro.contenido.id_matricula_informante == generar_id_matricula_medico(PEPPER_TEST, "MP12345")

    assert len(registro.contenido.medidas) == 3
    assert registro.contenido.secciones_texto[0].texto == "Funcion sistolica conservada"

    assert "medico_solicitante" not in registro.adicionales
    assert "Dr. Ana Lopez" not in str(registro.adicionales)
    assert "Dr. Carlos Gomez" not in str(registro.contenido)
    assert "MP12345" not in str(registro.contenido)
    assert registro.adicionales["peso"] == "70"


def test_eco_sin_firma_deja_campos_de_medico_informante_en_none() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(medidas=(), secciones_texto=(), firma=None),
        adicionales={},
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert registro.contenido.id_medico_informante is None
    assert registro.contenido.id_matricula_informante is None


def test_eco_texto_libre_con_dni_se_redacta_por_regex_incluso_sin_motor_inyectado() -> None:
    """Gap de PR7/PR8 (ver apply-progress): `secciones_texto` es texto libre dictado --
    puede traer PII incrustada por error (ver `pii/politica.py`, `_detecciones_texto_libre`).
    Incluso sin `motor_pii` inyectado (modo degradado, mismo principio que
    `observabilidad/bitacora_segura.py`), el regex de DNI debe redactar."""
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez"), dni=SecretStr("12345678")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(
            medidas=(),
            secciones_texto=(
                SeccionTextoEco(
                    nombre="CONCLUSIONES",
                    texto="Paciente con DNI 12.345.678 presenta funcion conservada",
                ),
            ),
            firma=None,
        ),
        adicionales={},
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    texto_redactado = registro.contenido.secciones_texto[0].texto
    assert "12.345.678" not in texto_redactado
    assert "[REDACTADO]" in texto_redactado


def test_eco_texto_libre_con_nombre_se_redacta_via_motor_pii_inyectado() -> None:
    """Con `motor_pii` inyectado (composición real del pipeline, ver `pipeline/ejecutor.py`),
    un nombre mencionado incidentalmente en la conclusión dictada también se redacta --
    cierra el gap explícito dejado por PR7/PR8 para que 11.3 (escaneo con `pii.motor`) pase."""
    from anonimizacion.pii.motor import MotorPii

    motor = MotorPii()

    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(
            medidas=(),
            secciones_texto=(
                SeccionTextoEco(
                    nombre="CONCLUSIONES",
                    texto="Revisado por el Dr. Roberto Fernandez, funcion sistolica conservada",
                ),
            ),
            firma=None,
        ),
        adicionales={},
    )

    registro = construir_registro(
        documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST, motor_pii=motor
    )

    texto_redactado = registro.contenido.secciones_texto[0].texto
    assert "Roberto Fernandez" not in texto_redactado


def test_construir_registro_propaga_hora_estudio_y_precision_sin_transformar() -> None:
    """Requirement: "Hora local sin conversión de huso" -- `construir_registro`
    propaga `hora_estudio`/`precision_hora` del `DocumentoParseado` al
    `RegistroAnonimizado` tal cual, sin transformarlos."""
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        hora_estudio=time(10, 22, 31),
        precision_hora=PrecisionHora.SEGUNDO,
        contenido=ContenidoEcg(
            vent_rate=None, pr_interval=None, qrs_duration=None, qt_qtc=None, ejes=None
        ),
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert registro.hora_estudio == time(10, 22, 31)
    assert registro.precision_hora is PrecisionHora.SEGUNDO


def test_construir_registro_propaga_ausencia_de_hora_sin_default() -> None:
    """Requirement: "Ausencia explícita cuando el documento no trae hora" --
    la ausencia (`None`/`AUSENTE`) también se propaga tal cual, nunca se
    reemplaza por un default."""
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECOCARDIOGRAMA,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEco(medidas=(), secciones_texto=(), firma=None),
    )

    registro = construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)

    assert registro.hora_estudio is None
    assert registro.precision_hora is PrecisionHora.AUSENTE


def test_claves_sin_id_paciente_resuelto_lanza_value_error() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.ECG,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=ContenidoEcg(
            vent_rate=None, pr_interval=None, qrs_duration=None, qt_qtc=None, ejes=None
        ),
    )
    claves_sin_resolver = ClavesPaciente(id_paciente=None, id_alt_paciente=None, version_clave=1)

    with pytest.raises(ValueError):
        construir_registro(documento, claves_sin_resolver, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)


def test_tipo_no_reconocido_lanza_value_error() -> None:
    documento = DocumentoParseado(
        tipo_documento=TipoDocumento.TIPO_NO_RECONOCIDO,
        version_esquema=1,
        identidad=IdentidadCruda(nombre=SecretStr("Juan Perez")),
        fecha_estudio=date(2024, 1, 10),
        contenido=None,
    )

    with pytest.raises(ValueError):
        construir_registro(documento, CLAVES_TEST, id_episodio=ID_EPISODIO_TEST, pepper=PEPPER_TEST)
