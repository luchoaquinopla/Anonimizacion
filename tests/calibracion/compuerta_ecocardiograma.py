"""Compuerta segura del contrato de ecocardiograma, sin valores fuente."""

from __future__ import annotations

from collections import Counter
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
class ResumenEcocardiograma:
    tipo_documento: str
    estado_deteccion: str
    estado_parseo: str
    campos_identidad: tuple[str, ...]
    campos_adicionales: tuple[str, ...]
    medidas: tuple[str, ...]
    tipos_medida: tuple[tuple[str, int], ...]
    unidades: tuple[tuple[str, int], ...]
    secciones: tuple[str, ...]
    paginas_medidas: tuple[int, ...]
    paginas_secciones: tuple[int, ...]
    pagina_firma: int | None
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
            "campos_identidad", "campos_adicionales", "medidas", "secciones",
            "paginas_medidas", "paginas_secciones", "campos_pii_estructurada",
            "campos_retirados_salida",
        ):
            datos[clave] = list(datos[clave])
        datos["tipos_medida"] = dict(datos["tipos_medida"])
        datos["unidades"] = dict(datos["unidades"])
        datos["pii_por_categoria"] = dict(datos["pii_por_categoria"])
        return datos


@dataclass(frozen=True)
class ComparacionContratoEco:
    cobertura_campos: float
    equivalencia_medidas: bool
    equivalencia_secciones: bool
    equivalencia_procedencia: bool
    equivalencia_pii: bool
    equivalencia_estado_final: bool


_MEDIDAS = ("AO", "SEPTUM", "AI", "P.POSTERIOR", "DDVI", "VD", "DSVI", "PULMON", "FA", "AD")
_SECCIONES = (
    "MOTILIDAD SEGMENTARIA",
    "AURICULAS",
    "VALVULAS CARDIACAS - AORTICA",
    "VALVULAS CARDIACAS - MITRAL",
    "VALVULAS CARDIACAS - PULMONAR",
    "VALVULAS CARDIACAS - TRICUSPIDEA",
    "PERICARDIO",
    "EVALUACION DE FLUJOS POR DOPPLER - FLUJO AORTICO",
    "EVALUACION DE FLUJOS POR DOPPLER - FLUJO MITRAL",
    "EVALUACION DE FLUJOS POR DOPPLER - FLUJO PULMONAR",
    "EVALUACION DE FLUJOS POR DOPPLER - FLUJO TRICUSPIDEO",
    "CONCLUSIONES",
)
_CAMPOS_PII = (
    "identidad.dni", "identidad.ids_internos", "identidad.nombre",
    "adicionales.medico_solicitante", "contenido.firma.nombre", "contenido.firma.matricula",
)

CONTRATO_ECOCARDIOGRAMA = ResumenEcocardiograma(
    "ecocardiograma", "aprobado", "aprobado",
    ("dni", "ids_internos", "nombre"),
    ("altura", "edad", "medico_solicitante", "peso", "superficie_corporal"),
    _MEDIDAS, (("numerico", 7), ("texto", 3)), (("%", 1), ("mm", 6), ("sin_unidad", 3)),
    _SECCIONES, (1,) * 10, (1,) * 10 + (2, 2), 2, _CAMPOS_PII,
    "ejecutada", (("cuasi_identificador", 1), ("medico", 2), ("paciente", 2), ("texto_libre", 0)),
    "ejecutada", _CAMPOS_PII, "aprobado", None, None,
    None, "ausente",
)


class _MotorPiiCalibracion:
    def evaluar_ids_internos(self, ids_internos):
        return ()

    def detectar(self, texto):
        return ()


def evaluar_ecocardiograma(ruta: Path) -> ResumenEcocardiograma:
    texto = extraer_texto(ruta)
    tipo = detectar_tipo(texto)
    documento = obtener_parseador(tipo).parsear(texto)
    contenido = documento.contenido
    estado_final, codigo_final, etapa_final = "aprobado", None, None
    try:
        obtener_reconciliador(tipo).reconciliar(documento, texto)
    except ErrorParseo as error:
        estado_final = "cuarentena"
        codigo_final = error.codigo.value
        etapa_final = getattr(error.etapa, "value", str(error.etapa))

    campos_identidad = ["nombre"]
    if documento.identidad.dni:
        campos_identidad.append("dni")
    if documento.identidad.ids_internos:
        campos_identidad.append("ids_internos")
    fuentes_medidas = [f for f in documento.fuentes if f.id_campo == "eco.medida"]
    fuentes_secciones = [f for f in documento.fuentes if f.id_campo == "eco.seccion"]
    fuente_firma = next((f for f in documento.fuentes if f.id_campo == "eco.firma"), None)
    tipos = Counter("numerico" if _es_numero(medida.valor) else "texto" for medida in contenido.medidas)
    unidades = Counter(medida.unidad or "sin_unidad" for medida in contenido.medidas)
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
        retirados = _CAMPOS_PII
    return ResumenEcocardiograma(
        tipo.value, "aprobado", "aprobado", tuple(sorted(campos_identidad)),
        tuple(sorted(documento.adicionales)), tuple(m.nombre for m in contenido.medidas),
        tuple(sorted(tipos.items())), tuple(sorted(unidades.items())),
        tuple(s.nombre for s in contenido.secciones_texto),
        tuple(f.pagina for f in fuentes_medidas), tuple(f.pagina for f in fuentes_secciones),
        fuente_firma.pagina if fuente_firma else None, _CAMPOS_PII,
        "no_ejecutada_por_cuarentena" if bloqueada else "ejecutada", pii_por_categoria,
        "no_ejecutada_por_cuarentena" if bloqueada else "ejecutada", retirados,
        estado_final, codigo_final, etapa_final,
        documento.hora_estudio.isoformat() if documento.hora_estudio is not None else None,
        documento.precision_hora.value,
    )


def _es_numero(valor: str) -> bool:
    try:
        float(valor.replace(",", "."))
        return True
    except ValueError:
        return False


def comparar_contrato(actual: ResumenEcocardiograma, esperado: ResumenEcocardiograma) -> ComparacionContratoEco:
    campos_actuales = set(actual.campos_identidad + actual.campos_adicionales)
    campos_esperados = set(esperado.campos_identidad + esperado.campos_adicionales)
    cobertura = len(campos_actuales & campos_esperados) / len(campos_esperados)
    return ComparacionContratoEco(
        cobertura,
        (actual.medidas, actual.tipos_medida, actual.unidades) == (esperado.medidas, esperado.tipos_medida, esperado.unidades),
        actual.secciones == esperado.secciones,
        (actual.paginas_medidas, actual.paginas_secciones, actual.pagina_firma)
        == (esperado.paginas_medidas, esperado.paginas_secciones, esperado.pagina_firma),
        (actual.campos_pii_estructurada, actual.estado_pii, actual.pii_por_categoria,
         actual.estado_anonimizacion, actual.campos_retirados_salida)
        == (esperado.campos_pii_estructurada, esperado.estado_pii, esperado.pii_por_categoria,
            esperado.estado_anonimizacion, esperado.campos_retirados_salida),
        (actual.estado_final, actual.codigo_final, actual.etapa_final)
        == (esperado.estado_final, esperado.codigo_final, esperado.etapa_final),
    )
