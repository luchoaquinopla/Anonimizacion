"""Adaptador de laboratorio limitado a contenido sintético en memoria."""

from collections.abc import Mapping

from ingesta_clinica.aplicacion.puertos.salida import ResultadoClasificacionFamilia
from ingesta_clinica.dominio.extraccion import ResolucionCampo, ResultadoExtraccion


ResultadoAdaptadorLaboratorio = ResultadoClasificacionFamilia


class AdaptadorFamiliaLaboratorio:
    """Clasifica marcadores sintéticos; no interpreta PDFs ni persiste entradas."""

    def extraer(self, contenido: bytes) -> ResultadoClasificacionFamilia:
        texto = contenido.decode("utf-8", errors="ignore")
        if "laboratorio" not in texto.lower():
            return self._resultado_no_compatible()

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

    def extraer_bloques(
        self, bloques: tuple[Mapping[str, object], ...]
    ) -> ResultadoClasificacionFamilia:
        """Convierte bloques estructurados sin conservar texto ni valores fuente."""
        if not self._contiene_cabecera_laboratorio(bloques):
            return self._resultado_no_compatible()

        filas_laboratorio = self._recolectar_filas_laboratorio(bloques)
        if filas_laboratorio is None:
            return self._resultado_no_compatible()

        candidatos_por_codigo, coordenadas = filas_laboratorio
        if not candidatos_por_codigo:
            return self._resultado_tabla_sin_filas()

        return self._resultado_laboratorio(candidatos_por_codigo, coordenadas)

    @staticmethod
    def _contiene_cabecera_laboratorio(
        bloques: tuple[Mapping[str, object], ...],
    ) -> bool:
        return any(
            bloque.get("tipo") == "cabecera_documento"
            and bloque.get("familia_documental") == "laboratorio"
            for bloque in bloques
        )

    @staticmethod
    def _recolectar_filas_laboratorio(
        bloques: tuple[Mapping[str, object], ...],
    ) -> tuple[dict[str, list[str]], list[tuple[int, int]]] | None:
        candidatos_por_codigo: dict[str, list[str]] = {}
        coordenadas: list[tuple[int, int]] = []
        try:
            for bloque in bloques:
                if bloque.get("tipo") != "fila_resultado_laboratorio":
                    continue

                numero_pagina = bloque.get("numero_pagina")
                indice_bloque = bloque.get("indice_bloque")
                codigo = bloque["codigo_campo"]
                estado = bloque["estado_extraido"]
                if (
                    type(numero_pagina) is not int
                    or type(indice_bloque) is not int
                    or not isinstance(codigo, str)
                    or not isinstance(estado, str)
                ):
                    return None

                ResolucionCampo(codigo=codigo, estado=estado)
                candidatos_por_codigo.setdefault(codigo, []).append(estado)
                coordenadas.append((numero_pagina, indice_bloque))
        except (KeyError, TypeError, ValueError):
            return None
        return candidatos_por_codigo, coordenadas

    @staticmethod
    def _resultado_laboratorio(
        candidatos_por_codigo: dict[str, list[str]],
        coordenadas: list[tuple[int, int]],
    ) -> ResultadoClasificacionFamilia:
        campos = tuple(
            ResolucionCampo(
                codigo=codigo,
                estado="ambiguo" if len(estados) > 1 else estados[0],
            )
            for codigo, estados in sorted(candidatos_por_codigo.items())
        )
        numero_pagina, indice_bloque = min(coordenadas)
        procedencia = {
            "numero_pagina": numero_pagina,
            "indice_bloque": indice_bloque,
        }
        return ResultadoClasificacionFamilia(
            es_laboratorio=True,
            codigo_rechazo=None,
            procedencia=procedencia,
            extraccion=ResultadoExtraccion(campos=campos, procedencia=procedencia),
        )

    @staticmethod
    def _resultado_tabla_sin_filas() -> ResultadoClasificacionFamilia:
        return ResultadoClasificacionFamilia(
            es_laboratorio=False,
            codigo_rechazo="TABLA_LABORATORIO_SIN_FILAS_RESULTADO",
            procedencia=None,
            extraccion=None,
        )

    @staticmethod
    def _resultado_no_compatible() -> ResultadoClasificacionFamilia:
        return ResultadoClasificacionFamilia(
            es_laboratorio=False,
            codigo_rechazo="FAMILIA_DOCUMENTO_NO_COMPATIBLE",
            procedencia=None,
            extraccion=None,
        )
