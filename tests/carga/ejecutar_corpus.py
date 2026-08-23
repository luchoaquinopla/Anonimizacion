"""Runner local y reproducible de los escalones de carga sintética."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from tests.fixtures.corpus_piloto import ejecutar_corpus_sintetico

_COMPOSICION_CARGA_1000 = (
    ("completo", 320),
    ("limite_7", 4),
    ("separacion_8", 3),
    ("faltante", 3),
    ("ambiguo", 2),
    ("corrupto", 1),
)


def crear_plan_carga(factor: int) -> tuple[str, ...]:
    return tuple(
        tipo
        for tipo, cantidad in _COMPOSICION_CARGA_1000
        for _ in range(cantidad * factor)
    )


PLAN_CARGA_1000 = crear_plan_carga(1)
DUPLICADOS_CARGA_1000 = 2


@dataclass(frozen=True)
class OraculoCarga:
    pdfs_entrada: int
    pdfs_staging_generados: int
    documentos_unicos: int
    duplicados_omitidos: int
    episodios_aprobados: int
    documentos_aprobados: int
    cuarentena_por_codigo: dict[str, int]
    reintentos: int
    pii_en_salida: int


ORACULO_CARGA_1000 = OraculoCarga(
    1_000,
    1_005,
    998,
    2,
    324,
    972,
    {"cobertura_ambigua": 8, "cobertura_incompleta": 17, "parseo_incompleto": 1},
    0,
    0,
)


def escalar_oraculo(oraculo: OraculoCarga, factor: int) -> OraculoCarga:
    return OraculoCarga(
        pdfs_entrada=oraculo.pdfs_entrada * factor,
        pdfs_staging_generados=oraculo.pdfs_staging_generados * factor,
        documentos_unicos=oraculo.documentos_unicos * factor,
        duplicados_omitidos=oraculo.duplicados_omitidos * factor,
        episodios_aprobados=oraculo.episodios_aprobados * factor,
        documentos_aprobados=oraculo.documentos_aprobados * factor,
        cuarentena_por_codigo={
            codigo: cantidad * factor
            for codigo, cantidad in oraculo.cuarentena_por_codigo.items()
        },
        reintentos=oraculo.reintentos * factor,
        pii_en_salida=oraculo.pii_en_salida,
    )


PLAN_CARGA_10000 = crear_plan_carga(10)
DUPLICADOS_CARGA_10000 = DUPLICADOS_CARGA_1000 * 10
ORACULO_CARGA_10000 = escalar_oraculo(ORACULO_CARGA_1000, 10)


@dataclass(frozen=True)
class ResumenCarga:
    pdfs_entrada: int
    pdfs_staging_generados: int
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
    throughput_pdfs_entrada_segundo: float
    throughput_documentos_unicos_segundo: float
    memoria_pico_lifetime_proceso_bytes: int
    pii_en_salida: int
    oraculo_validado: bool

    def como_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PreflightCarga:
    espacio_disponible_inicial_bytes: int
    memoria_disponible_inicial_bytes: int
    disco_estimado_bytes: int
    memoria_estimada_bytes: int
    tiempo_estimado_segundos: float
    aprobado: bool

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


def _memoria_disponible_bytes() -> int:
    if os.name != "nt":
        paginas = os.sysconf("SC_AVPHYS_PAGES")
        return int(paginas * os.sysconf("SC_PAGE_SIZE"))

    class EstadoMemoria(ctypes.Structure):
        _fields_ = [
            ("longitud", ctypes.c_ulong),
            ("carga", ctypes.c_ulong),
            *((nombre, ctypes.c_ulonglong) for nombre in (
                "fisica_total", "fisica_disponible", "pagina_total", "pagina_disponible",
                "virtual_total", "virtual_disponible", "virtual_extendida_disponible",
            )),
        ]

    estado = EstadoMemoria()
    estado.longitud = ctypes.sizeof(estado)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
        raise OSError("no se pudo medir la memoria disponible")
    return int(estado.fisica_disponible)


def evaluar_preflight(salida: Path, oraculo: OraculoCarga) -> PreflightCarga:
    espacio = shutil.disk_usage(salida.resolve().anchor).free
    memoria = _memoria_disponible_bytes()
    disco_estimado = int(
        (oraculo.pdfs_entrada + oraculo.pdfs_staging_generados) * 45_131 * 1.2
    )
    factor = oraculo.pdfs_entrada / ORACULO_CARGA_1000.pdfs_entrada
    memoria_estimada = int(145_432_576 * factor)
    tiempo_estimado = round(226.541137 * factor, 6)
    return PreflightCarga(
        espacio,
        memoria,
        disco_estimado,
        memoria_estimada,
        tiempo_estimado,
        espacio >= disco_estimado and memoria >= memoria_estimada,
    )


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
        resumen.pdfs_entrada,
        sum(1 for _ in (directorio / "generados").rglob("*.pdf")),
        resumen.documentos_inventariados,
        resumen.pdfs_entrada - resumen.documentos_inventariados,
        resumen.episodios_aprobados,
        resumen.documentos_publicados,
        resumen.cuarentena_por_codigo,
        resumen.reintentos,
        resumen.pii_en_salida,
    )
    if actual != oraculo:
        raise AssertionError("el resultado no coincide con el oraculo de carga seguro")
    return ResumenCarga(
        pdfs_entrada=resumen.pdfs_entrada,
        pdfs_staging_generados=actual.pdfs_staging_generados,
        documentos_unicos=resumen.documentos_inventariados,
        duplicados_omitidos=resumen.pdfs_entrada - resumen.documentos_inventariados,
        episodios_aprobados=resumen.episodios_aprobados,
        documentos_aprobados=resumen.documentos_publicados,
        documentos_en_cuarentena=resumen.documentos_en_cuarentena,
        cuarentena_por_codigo=resumen.cuarentena_por_codigo,
        cuarentenas_esperadas=sum(oraculo.cuarentena_por_codigo.values()),
        fallos_inesperados=0,
        reintentos=resumen.reintentos,
        tiempo_total_segundos=round(duracion, 6),
        throughput_pdfs_entrada_segundo=round(resumen.pdfs_entrada / duracion, 3),
        throughput_documentos_unicos_segundo=round(resumen.documentos_inventariados / duracion, 3),
        memoria_pico_lifetime_proceso_bytes=_memoria_pico_proceso_bytes(),
        pii_en_salida=resumen.pii_en_salida,
        oraculo_validado=True,
    )


def _normalizar_corrida(corrida: dict[str, object]) -> dict[str, object]:
    normalizada = dict(corrida)
    if "pdfs_generados" in normalizada:
        entradas = int(normalizada.pop("pdfs_generados"))
        normalizada["pdfs_entrada"] = entradas
        normalizada.setdefault("pdfs_staging_generados", round(entradas * 1.005))
    if "throughput_archivos_fisicos_segundo" in normalizada:
        normalizada["throughput_pdfs_entrada_segundo"] = normalizada.pop(
            "throughput_archivos_fisicos_segundo"
        )
    return normalizada


def _escribir_reporte(contenido: dict[str, object], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(contenido, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def migrar_reporte_legacy(
    ruta: Path, oraculo: OraculoCarga | None = None
) -> None:
    contenido = json.loads(ruta.read_text(encoding="utf-8"))
    contenido["ultima_corrida"] = _normalizar_corrida(contenido["ultima_corrida"])
    contenido["corridas"] = [
        _normalizar_corrida(corrida) for corrida in contenido.get("corridas", [])
    ]
    if oraculo is not None:
        contenido["preflight"] = evaluar_preflight(ruta.parent, oraculo).como_dict()
    _escribir_reporte(contenido, ruta)


def guardar_reporte(
    resultado: ResumenCarga, ruta: Path, preflight: PreflightCarga | None = None
) -> None:
    corridas: list[dict[str, object]] = []
    if ruta.exists():
        anterior = json.loads(ruta.read_text(encoding="utf-8"))
        corridas = [_normalizar_corrida(corrida) for corrida in anterior.get("corridas", [anterior])]
        corridas = [corrida for corrida in corridas if corrida.get("oraculo_validado") is True]
    actual = resultado.como_dict()
    if not corridas or corridas[-1] != actual:
        corridas.append(actual)
    contenido = {"ultima_corrida": actual, "corridas": corridas}
    if preflight is not None:
        contenido["preflight"] = preflight.como_dict()
    _escribir_reporte(contenido, ruta)


def ejecutar_cli(
    salida: Path,
    *,
    semilla: int,
    tipos_caso: tuple[str, ...] = PLAN_CARGA_1000,
    duplicados: int = DUPLICADOS_CARGA_1000,
    oraculo: OraculoCarga = ORACULO_CARGA_1000,
) -> ResumenCarga:
    preflight = evaluar_preflight(salida, oraculo)
    if not preflight.aprobado:
        raise RuntimeError("preflight de carga rechazado")
    directorio = salida / "corridas" / uuid4().hex
    resultado = ejecutar_carga(
        directorio,
        semilla=semilla,
        tipos_caso=tipos_caso,
        duplicados=duplicados,
        oraculo=oraculo,
    )
    guardar_reporte(resultado, salida / "reporte_seguro.json", preflight)
    return resultado


if __name__ == "__main__":
    salida = Path("tmp/carga_1000")
    resultado = ejecutar_cli(salida, semilla=20260823)
    print(json.dumps(resultado.como_dict(), indent=2))
