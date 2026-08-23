"""Runner local y reproducible del escalón de carga de 1.000 PDFs."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from tests.fixtures.corpus_piloto import ejecutar_corpus_sintetico

PLAN_CARGA_1000 = (
    *("completo",) * 320,
    *("limite_7",) * 4,
    *("separacion_8",) * 3,
    *("faltante",) * 3,
    *("ambiguo",) * 2,
    "corrupto",
)
DUPLICADOS_CARGA_1000 = 2


@dataclass(frozen=True)
class OraculoCarga:
    pdfs_generados: int
    documentos_unicos: int
    duplicados_omitidos: int
    episodios_aprobados: int
    documentos_aprobados: int
    cuarentena_por_codigo: dict[str, int]
    reintentos: int
    pii_en_salida: int


ORACULO_CARGA_1000 = OraculoCarga(
    1_000,
    998,
    2,
    324,
    972,
    {"cobertura_ambigua": 8, "cobertura_incompleta": 17, "parseo_incompleto": 1},
    0,
    0,
)


@dataclass(frozen=True)
class ResumenCarga:
    pdfs_generados: int
    documentos_unicos: int
    duplicados_omitidos: int
    episodios_aprobados: int
    documentos_aprobados: int
    documentos_en_cuarentena: int
    cuarentena_por_codigo: dict[str, int]
    cuarentenas_esperadas: int
    fallos_inesperados: int
    reintentos: int
    tiempo_total_segundos: float
    throughput_archivos_fisicos_segundo: float
    throughput_documentos_unicos_segundo: float
    memoria_pico_lifetime_proceso_bytes: int
    pii_en_salida: int
    oraculo_validado: bool

    def como_dict(self) -> dict[str, object]:
        return asdict(self)


def _memoria_pico_proceso_bytes() -> int:
    if os.name != "nt":
        import resource

        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(pico if sys.platform == "darwin" else pico * 1024)

    class ContadoresMemoria(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("fallos_pagina", ctypes.c_ulong),
            *((nombre, ctypes.c_size_t) for nombre in (
                "pico_trabajo", "trabajo", "pico_paginado", "paginado",
                "pico_no_paginado", "no_paginado", "archivo_pagina", "pico_archivo_pagina",
            )),
        ]

    contadores = ContadoresMemoria()
    contadores.cb = ctypes.sizeof(contadores)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    proceso = ctypes.windll.kernel32.GetCurrentProcess()
    funcion = ctypes.windll.psapi.GetProcessMemoryInfo
    funcion.argtypes = (ctypes.c_void_p, ctypes.POINTER(ContadoresMemoria), ctypes.c_ulong)
    funcion.restype = ctypes.c_int
    if not funcion(proceso, ctypes.byref(contadores), contadores.cb):
        raise OSError("no se pudo medir la memoria del proceso")
    return int(contadores.pico_trabajo)


def ejecutar_carga(
    directorio: Path,
    *,
    semilla: int,
    tipos_caso: tuple[str, ...] = PLAN_CARGA_1000,
    duplicados: int = DUPLICADOS_CARGA_1000,
    oraculo: OraculoCarga = ORACULO_CARGA_1000,
) -> ResumenCarga:
    inicio = perf_counter()
    resumen = ejecutar_corpus_sintetico(
        directorio, semilla=semilla, tipos_caso=tipos_caso, duplicados=duplicados
    )
    duracion = perf_counter() - inicio
    actual = OraculoCarga(
        resumen.archivos_en_disco,
        resumen.documentos_inventariados,
        resumen.archivos_en_disco - resumen.documentos_inventariados,
        resumen.episodios_aprobados,
        resumen.documentos_publicados,
        resumen.cuarentena_por_codigo,
        resumen.reintentos,
        resumen.pii_en_salida,
    )
    if actual != oraculo:
        raise AssertionError("el resultado no coincide con el oraculo de carga seguro")
    return ResumenCarga(
        pdfs_generados=resumen.archivos_en_disco,
        documentos_unicos=resumen.documentos_inventariados,
        duplicados_omitidos=resumen.archivos_en_disco - resumen.documentos_inventariados,
        episodios_aprobados=resumen.episodios_aprobados,
        documentos_aprobados=resumen.documentos_publicados,
        documentos_en_cuarentena=resumen.documentos_en_cuarentena,
        cuarentena_por_codigo=resumen.cuarentena_por_codigo,
        cuarentenas_esperadas=sum(oraculo.cuarentena_por_codigo.values()),
        fallos_inesperados=0,
        reintentos=resumen.reintentos,
        tiempo_total_segundos=round(duracion, 6),
        throughput_archivos_fisicos_segundo=round(resumen.archivos_en_disco / duracion, 3),
        throughput_documentos_unicos_segundo=round(resumen.documentos_inventariados / duracion, 3),
        memoria_pico_lifetime_proceso_bytes=_memoria_pico_proceso_bytes(),
        pii_en_salida=resumen.pii_en_salida,
        oraculo_validado=True,
    )


def guardar_reporte(resultado: ResumenCarga, ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    corridas: list[dict[str, object]] = []
    if ruta.exists():
        anterior = json.loads(ruta.read_text(encoding="utf-8"))
        corridas = anterior.get("corridas", [anterior])
        corridas = [corrida for corrida in corridas if corrida.get("oraculo_validado") is True]
    actual = resultado.como_dict()
    if not corridas or corridas[-1] != actual:
        corridas.append(actual)
    contenido = {"ultima_corrida": actual, "corridas": corridas}
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(contenido, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def ejecutar_cli(
    salida: Path,
    *,
    semilla: int,
    tipos_caso: tuple[str, ...] = PLAN_CARGA_1000,
    duplicados: int = DUPLICADOS_CARGA_1000,
    oraculo: OraculoCarga = ORACULO_CARGA_1000,
) -> ResumenCarga:
    directorio = salida / "corridas" / uuid4().hex
    resultado = ejecutar_carga(
        directorio,
        semilla=semilla,
        tipos_caso=tipos_caso,
        duplicados=duplicados,
        oraculo=oraculo,
    )
    guardar_reporte(resultado, salida / "reporte_seguro.json")
    return resultado


if __name__ == "__main__":
    salida = Path("tmp/carga_1000")
    resultado = ejecutar_cli(salida, semilla=20260823)
    print(json.dumps(resultado.como_dict(), indent=2))
