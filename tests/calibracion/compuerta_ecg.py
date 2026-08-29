"""Compuerta segura del contrato ECG; excluye valores y señal clínica."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.dominio.errores import ErrorParseo
from anonimizacion.dominio.modelos import ClavesPaciente
from anonimizacion.extraccion.texto_pymupdf import extraer_texto
from anonimizacion.parseo.registro import obtener_parseador
from anonimizacion.pii.politica import clasificar
from anonimizacion.reconciliacion.registro import obtener_reconciliador
from anonimizacion.salida.constructor_registro import construir_registro


@dataclass(frozen=True)
class ResumenEcg:
    tipo_documento: str
    estado_deteccion: str
    estado_parseo: str
    campos_identidad: tuple[str, ...]
    campos_adicionales: tuple[str, ...]
    metricas: tuple[str, ...]
    formatos_metricas: tuple[tuple[str, str], ...]
    paginas_metricas: tuple[int, ...]
    advertencia_equipo: str | None
    imagen_trazado: str
    campos_pii_estructurada: tuple[str, ...]
    estado_pii: str
    pii_por_categoria: tuple[tuple[str, int], ...]
    estado_anonimizacion: str
    campos_retirados_salida: tuple[str, ...]
    estado_final: str
    codigo_final: str | None
    etapa_final: str | None
    hora_estudio: str | None
    precision_hora: str

    def como_dict(self) -> dict[str, object]:
        datos = asdict(self)
        for clave in (
            "campos_identidad", "campos_adicionales", "metricas", "paginas_metricas",
            "campos_pii_estructurada", "campos_retirados_salida",
        ):
            datos[clave] = list(datos[clave])
        datos["formatos_metricas"] = dict(datos["formatos_metricas"])
        datos["pii_por_categoria"] = dict(datos["pii_por_categoria"])
        return datos


@dataclass(frozen=True)
class ComparacionContratoEcg:
    cobertura_campos: float
    equivalencia_metricas: bool
    equivalencia_procedencia: bool
    equivalencia_advertencia: bool
    equivalencia_pii: bool
    equivalencia_estado_final: bool


_METRICAS = ("vent_rate", "pr_interval", "qrs_duration", "qt_qtc", "ejes")
_CAMPOS_PII = (
    "identidad.fecha_nac", "identidad.ids_internos", "identidad.nombre",
    "adicionales.medico_derivante",
)

CONTRATO_ECG = ResumenEcg(
    "ecg", "aprobado", "aprobado", ("fecha_nac", "ids_internos", "nombre"),
    ("advertencia_equipo", "edad", "institucion", "medico_derivante", "sexo", "tecnico", "test_ind"),
    _METRICAS,
    (("ejes", "triple_numerico"), ("pr_interval", "escalar_numerico"),
     ("qrs_duration", "escalar_numerico"), ("qt_qtc", "par_numerico"),
     ("vent_rate", "escalar_numerico")),
    (1, 1, 1, 1, 1), "PID_NAME_MISMATCH", "fuera_de_contrato_clinico", _CAMPOS_PII,
    "ejecutada", (("cuasi_identificador", 1), ("medico", 1), ("paciente", 2), ("texto_libre", 0)),
    "ejecutada", _CAMPOS_PII, "aprobado", None, None,
    "08:30:00", "segundo",
)


class _MotorPiiCalibracion:
    def evaluar_ids_internos(self, ids_internos):
        return ()

    def detectar(self, texto):
        return ()


def _formato_metrica(valor: str) -> str:
    partes = valor.replace("/", " ").split()
    try:
        for parte in partes:
            float(parte.replace(",", "."))
    except ValueError:
        return "texto"
    if "/" in valor and len(partes) == 2:
        return "par_numerico"
    if len(partes) == 3:
        return "triple_numerico"
    return "escalar_numerico" if len(partes) == 1 else "texto"


def evaluar_ecg(ruta: Path) -> ResumenEcg:
    texto = extraer_texto(ruta)
    tipo = detectar_tipo(texto)
    documento = obtener_parseador(tipo).parsear(texto)
    contenido = documento.contenido
    campos_identidad = ["nombre"]
    if documento.identidad.fecha_nac is not None:
        campos_identidad.append("fecha_nac")
    if documento.identidad.ids_internos:
        campos_identidad.append("ids_internos")
    campos_pii = tuple(
        campo
        for campo, presente in (
            ("identidad.fecha_nac", documento.identidad.fecha_nac is not None),
            ("identidad.ids_internos", bool(documento.identidad.ids_internos)),
            ("identidad.nombre", True),
            ("adicionales.medico_derivante", "medico_derivante" in documento.adicionales),
        )
        if presente
    )
    metricas = tuple(nombre for nombre in _METRICAS if getattr(contenido, nombre) is not None)
    formatos = tuple(sorted((nombre, _formato_metrica(getattr(contenido, nombre))) for nombre in metricas))
    fuentes = {fuente.id_campo: fuente.pagina for fuente in documento.fuentes}
    estado_final, codigo_final, etapa_final = "aprobado", None, None
    try:
        obtener_reconciliador(tipo).reconciliar(documento, texto)
    except ErrorParseo as error:
        estado_final = "cuarentena"
        codigo_final = error.codigo.value
        etapa_final = getattr(error.etapa, "value", str(error.etapa))
    bloqueada = estado_final == "cuarentena"
    pii_por_categoria: tuple[tuple[str, int], ...] = ()
    retirados: tuple[str, ...] = ()
    if not bloqueada:
        politica = clasificar(documento, _MotorPiiCalibracion())
        pii_por_categoria = tuple(sorted({
            "paciente": len(politica.elementos_paciente),
            "medico": len(politica.elementos_medico),
            "cuasi_identificador": len(politica.cuasi_identificadores),
            "texto_libre": len(politica.detecciones_texto_libre),
        }.items()))
        construir_registro(
            documento, ClavesPaciente("paciente-calibracion", "alternativa-calibracion", 1),
            id_episodio="episodio-calibracion", pepper=b"pepper-sintetico-de-calibracion",
            motor_pii=_MotorPiiCalibracion(),
        )
        retirados = campos_pii
    return ResumenEcg(
        tipo.value, "aprobado", "aprobado", tuple(sorted(campos_identidad)),
        tuple(sorted(documento.adicionales)), metricas, formatos,
        tuple(fuentes[f"ecg.{nombre}"] for nombre in metricas),
        documento.adicionales.get("advertencia_equipo"), "fuera_de_contrato_clinico", campos_pii,
        "no_ejecutada_por_cuarentena" if bloqueada else "ejecutada", pii_por_categoria,
        "no_ejecutada_por_cuarentena" if bloqueada else "ejecutada", retirados,
        estado_final, codigo_final, etapa_final,
        documento.hora_estudio.isoformat() if documento.hora_estudio is not None else None,
        documento.precision_hora.value,
    )


def comparar_contrato(actual: ResumenEcg, esperado: ResumenEcg) -> ComparacionContratoEcg:
    campos_actuales = set(actual.campos_identidad + actual.campos_adicionales)
    campos_esperados = set(esperado.campos_identidad + esperado.campos_adicionales)
    return ComparacionContratoEcg(
        len(campos_actuales & campos_esperados) / len(campos_esperados),
        (actual.metricas, actual.formatos_metricas, actual.imagen_trazado)
        == (esperado.metricas, esperado.formatos_metricas, esperado.imagen_trazado),
        actual.paginas_metricas == esperado.paginas_metricas,
        actual.advertencia_equipo == esperado.advertencia_equipo,
        (actual.campos_pii_estructurada, actual.estado_pii, actual.pii_por_categoria,
         actual.estado_anonimizacion, actual.campos_retirados_salida)
        == (esperado.campos_pii_estructurada, esperado.estado_pii, esperado.pii_por_categoria,
            esperado.estado_anonimizacion, esperado.campos_retirados_salida),
        (actual.estado_final, actual.codigo_final, actual.etapa_final)
        == (esperado.estado_final, esperado.codigo_final, esperado.etapa_final),
    )
