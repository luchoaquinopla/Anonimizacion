"""Compuerta segura y reproducible del contrato de laboratorio.

El contrato contiene únicamente nombres de campos, secciones, determinaciones,
conteos y decisiones del pipeline. Nunca conserva valores del PDF de referencia.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import unicodedata

from anonimizacion.deteccion.detector_tipo import detectar_tipo
from anonimizacion.dominio.modelos import ClavesPaciente
from anonimizacion.dominio.errores import ErrorParseo
from anonimizacion.extraccion.texto_pymupdf import extraer_texto
from anonimizacion.parseo.registro import obtener_parseador
from anonimizacion.pii.politica import clasificar
from anonimizacion.reconciliacion.normalizacion import normalizar_texto
from anonimizacion.pseudonimizacion.claves import generar_clave_documento
from anonimizacion.reconciliacion.registro import obtener_reconciliador
from anonimizacion.salida.constructor_registro import construir_registro

_PEPPER_CALIBRACION = b"pepper-sintetico-de-calibracion"
_SHA256_SINTETICO_CALIBRACION = "d" * 64  # huella inventada de 64 hex, ningún valor real

def _normalizar_etiqueta(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", normalizar_texto(valor))
    return "".join(caracter for caracter in normalizado if not unicodedata.combining(caracter))

@dataclass(frozen=True)
class ResumenLaboratorio:
    tipo_documento: str
    estado_deteccion: str
    estado_parseo: str
    campos_identidad: tuple[str, ...]
    campos_adicionales: tuple[str, ...]
    secciones: tuple[str, ...]
    determinaciones: tuple[str, ...]
    tipos_resultado: tuple[tuple[str, int], ...]
    resultados_con_unidad: int
    resultados_con_referencia: int
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
            "campos_identidad",
            "campos_adicionales",
            "secciones",
            "determinaciones",
            "campos_pii_estructurada",
            "campos_retirados_salida",
        ):
            datos[clave] = list(datos[clave])
        datos["tipos_resultado"] = dict(datos["tipos_resultado"])
        datos["pii_por_categoria"] = dict(datos["pii_por_categoria"])
        return datos

@dataclass(frozen=True)
class ComparacionContrato:
    cobertura_campos: float
    cobertura_secciones: float
    cobertura_determinaciones: float
    equivalencia_tipos: bool
    equivalencia_pii: bool
    equivalencia_estado_final: bool

    def como_dict(self) -> dict[str, object]:
        return asdict(self)


_DETERMINACIONES = (
    "basofilos",
    "cayados",
    "conc. de hba corpuscular media",
    "creatinina serica",
    "eosinofilos",
    "eritrosedimentacion",
    "filtrado glomerular estimado (ckd-epi 2021)",
    "globulos blancos",
    "globulos rojos",
    "glucemia",
    "granulocitos inmaduros",
    "hematocrito",
    "hemoglobina",
    "hemoglobina corpuscular media",
    "linfocitos",
    "monocitos",
    "neutrofilos",
    "plaquetas",
    "potasio",
    "r",
    "rdw-cv",
    "rdw-sd",
    "rin",
    "sodio",
    "tiempo de protrombina",
    "tiempo de tromboplastina aptt",
    "uremia",
    "volumen corpuscular medio",
    "volumen plaquetario medio",
)

CONTRATO_LABORATORIO = ResumenLaboratorio(
    tipo_documento="laboratorio",
    estado_deteccion="aprobado",
    estado_parseo="aprobado",
    campos_identidad=("dni", "fecha_nac", "ids_internos", "nombre"),
    campos_adicionales=("edad", "medico_derivante", "origen"),
    secciones=("formula leucocitaria", "hematologia", "hemograma", "hemostasia", "ionograma", "quimica clinica"),
    determinaciones=_DETERMINACIONES,
    tipos_resultado=(("numerico", 36),),
    resultados_con_unidad=34,
    resultados_con_referencia=33,
    campos_pii_estructurada=(
        "identidad.dni",
        "identidad.fecha_nac",
        "identidad.ids_internos",
        "identidad.nombre",
        "adicionales.medico_derivante",
    ),
    estado_pii="ejecutada",
    pii_por_categoria=(("cuasi_identificador", 1), ("medico", 1), ("paciente", 3), ("texto_libre", 0)),
    estado_anonimizacion="ejecutada",
    campos_retirados_salida=(
        "identidad.dni",
        "identidad.fecha_nac",
        "identidad.ids_internos",
        "identidad.nombre",
        "adicionales.medico_derivante",
    ),
    estado_final="aprobado",
    codigo_final=None,
    etapa_final=None,
    hora_estudio="08:30:00",
    precision_hora="minuto",
)


class _MotorPiiCalibracion:
    """Doble offline: la compuerta valida política, no calidad del modelo NER."""

    def evaluar_ids_internos(self, ids_internos: tuple[str, ...]) -> tuple[object, ...]:
        return ()

    def detectar(self, texto: str) -> tuple[object, ...]:
        return ()


def evaluar_laboratorio(ruta: Path) -> ResumenLaboratorio:
    texto = extraer_texto(ruta)
    tipo = detectar_tipo(texto)
    documento = obtener_parseador(tipo).parsear(texto)
    contenido = documento.contenido
    campos_identidad = ["nombre"]
    if documento.identidad.dni is not None:
        campos_identidad.append("dni")
    if documento.identidad.fecha_nac is not None:
        campos_identidad.append("fecha_nac")
    if documento.identidad.ids_internos:
        campos_identidad.append("ids_internos")
    campos_pii = [
        campo
        for campo, presente in (
            ("identidad.dni", documento.identidad.dni is not None),
            ("identidad.fecha_nac", documento.identidad.fecha_nac is not None),
            ("identidad.ids_internos", bool(documento.identidad.ids_internos)),
            ("identidad.nombre", True),
            ("adicionales.medico_derivante", "medico_derivante" in documento.adicionales),
        )
        if presente
    ]
    tipos = {"numerico": 0, "texto": 0}
    for fila in contenido.resultados:
        try:
            float(fila.resultado.replace(",", "."))
            tipos["numerico"] += 1
        except ValueError:
            tipos["texto"] += 1
    tipos = {clave: cantidad for clave, cantidad in tipos.items() if cantidad}
    estado_final = "aprobado"
    codigo_final = None
    etapa_final = None
    try:
        obtener_reconciliador(tipo).reconciliar(documento, texto)
    except ErrorParseo as error:
        estado_final = "cuarentena"
        codigo_final = error.codigo.value
        etapa_final = getattr(error.etapa, "value", str(error.etapa))
    bloqueada = estado_final == "cuarentena"
    pii_por_categoria: tuple[tuple[str, int], ...] = ()
    campos_retirados: tuple[str, ...] = ()
    if not bloqueada:
        politica = clasificar(documento, _MotorPiiCalibracion())
        pii_por_categoria = tuple(sorted({
            "paciente": len(politica.elementos_paciente),
            "medico": len(politica.elementos_medico),
            "cuasi_identificador": len(politica.cuasi_identificadores),
            "texto_libre": len(politica.detecciones_texto_libre),
        }.items()))
        construir_registro(
            documento,
            ClavesPaciente("paciente-calibracion", "alternativa-calibracion", 1),
            id_episodio="episodio-calibracion",
            pepper=_PEPPER_CALIBRACION,
            clave_documento=generar_clave_documento(_PEPPER_CALIBRACION, _SHA256_SINTETICO_CALIBRACION),
        )
        campos_retirados = tuple(campos_pii)
    return ResumenLaboratorio(
        tipo_documento=tipo.value,
        estado_deteccion="aprobado",
        estado_parseo="aprobado",
        campos_identidad=tuple(sorted(campos_identidad)),
        campos_adicionales=tuple(sorted(documento.adicionales)),
        secciones=tuple(sorted({_normalizar_etiqueta(fila.seccion) for fila in contenido.resultados})),
        determinaciones=tuple(sorted({_normalizar_etiqueta(fila.prueba) for fila in contenido.resultados})),
        tipos_resultado=tuple(sorted(tipos.items())),
        resultados_con_unidad=sum(fila.unidades is not None for fila in contenido.resultados),
        resultados_con_referencia=sum(fila.valores_referencia is not None for fila in contenido.resultados),
        campos_pii_estructurada=tuple(campos_pii),
        estado_pii="no_ejecutada_por_cuarentena" if bloqueada else "ejecutada",
        pii_por_categoria=pii_por_categoria,
        estado_anonimizacion="no_ejecutada_por_cuarentena" if bloqueada else "ejecutada",
        campos_retirados_salida=campos_retirados,
        estado_final=estado_final,
        codigo_final=codigo_final,
        etapa_final=etapa_final,
        hora_estudio=documento.hora_estudio.isoformat() if documento.hora_estudio is not None else None,
        precision_hora=documento.precision_hora.value,
    )


def _cobertura(actuales: tuple[str, ...], requeridos: tuple[str, ...]) -> float:
    if not requeridos:
        return 1.0
    return len(set(actuales) & set(requeridos)) / len(set(requeridos))


def comparar_contrato(actual: ResumenLaboratorio, esperado: ResumenLaboratorio) -> ComparacionContrato:
    campos_actuales = actual.campos_identidad + actual.campos_adicionales
    campos_esperados = esperado.campos_identidad + esperado.campos_adicionales
    return ComparacionContrato(
        cobertura_campos=_cobertura(campos_actuales, campos_esperados),
        cobertura_secciones=_cobertura(actual.secciones, esperado.secciones),
        cobertura_determinaciones=_cobertura(actual.determinaciones, esperado.determinaciones),
        equivalencia_tipos=(
            actual.tipo_documento == esperado.tipo_documento
            and actual.tipos_resultado == esperado.tipos_resultado
            and actual.resultados_con_unidad == esperado.resultados_con_unidad
            and actual.resultados_con_referencia == esperado.resultados_con_referencia
        ),
        equivalencia_pii=(
            actual.campos_pii_estructurada == esperado.campos_pii_estructurada
            and actual.estado_pii == esperado.estado_pii
            and actual.pii_por_categoria == esperado.pii_por_categoria
            and actual.estado_anonimizacion == esperado.estado_anonimizacion
            and actual.campos_retirados_salida == esperado.campos_retirados_salida
        ),
        equivalencia_estado_final=(
            actual.estado_final == esperado.estado_final
            and actual.codigo_final == esperado.codigo_final
            and actual.etapa_final == esperado.etapa_final
        ),
    )
