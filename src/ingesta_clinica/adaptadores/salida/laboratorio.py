"""Adaptador de laboratorio limitado a contenido sintético en memoria."""

from ingesta_clinica.aplicacion.puertos.salida import ResultadoClasificacionFamilia
from ingesta_clinica.dominio.extraccion import ResolucionCampo, ResultadoExtraccion


ResultadoAdaptadorLaboratorio = ResultadoClasificacionFamilia


class AdaptadorFamiliaLaboratorio:
    """Clasifica marcadores sintéticos; no interpreta PDFs ni persiste entradas."""

    def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
        texto = contenido.decode("utf-8", errors="ignore")
        if "laboratorio" not in texto.lower():
            return ResultadoClasificacionFamilia(
                es_laboratorio=False,
                codigo_rechazo="FAMILIA_DOCUMENTO_NO_COMPATIBLE",
                procedencia=None,
                extraccion=None,
            )

        procedencia = {"numero_pagina": 1, "indice_bloque": 0}
        estado = "verificado" if "marcador_alfa" in texto else "no_presente"
        return ResultadoClasificacionFamilia(
            es_laboratorio=True,
            codigo_rechazo=None,
            procedencia=procedencia,
            extraccion=ResultadoExtraccion(
                campos=(
                    ResolucionCampo(codigo="marcador_laboratorio_alfa", estado=estado),
                ),
                procedencia=procedencia,
            ),
        )
