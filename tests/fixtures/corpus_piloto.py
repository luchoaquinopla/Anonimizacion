"""Corpus piloto adversarial offline con oráculo agregado y sin PII."""

from __future__ import annotations

import shutil
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from anonimizacion.dominio.modelos import ClavesPaciente, RegistroAnonimizado
from anonimizacion.ingesta.fuente import FuenteLocal, HuellasEnMemoria
from anonimizacion.pipeline.ejecutor import ItemLote
from anonimizacion.trabajadores.tareas import construir_fabrica_ejecutor
from anonimizacion.pipeline.resultado import ExitoDocumento

from .pdf_sintetico import crear_pdf_corrupto, generar_corpus_clinico


@dataclass(frozen=True)
class ResumenPiloto:
    casos: int
    pdfs_entrada: int
    documentos_inventariados: int
    episodios_aprobados: int
    documentos_publicados: int
    documentos_en_cuarentena: int
    cuarentena_por_codigo: dict[str, int]
    registros_inspeccionados: int
    valores_pii_verificados: int
    pii_en_salida: int
    reintentos: int

    def como_dict(self) -> dict[str, object]:
        return asdict(self)


class _MotorPiiOffline:
    def evaluar_ids_internos(self, ids_internos):
        return ()

    def detectar(self, texto):
        return ()


class _DestinoMemoria:
    def __init__(self) -> None:
        self.episodios: set[str] = set()
        self.registros: list[RegistroAnonimizado] = []

    def escribir_episodio(self, *, id_episodio: str, id_paciente: str, fecha_ancla: date) -> None:
        self.episodios.add(id_episodio)

    def escribir_registro(self, registro: RegistroAnonimizado) -> None:
        self.registros.append(registro)


class _CuarentenaMemoria:
    def __init__(self) -> None:
        self.errores = []

    def registrar(self, error) -> None:
        self.errores.append(error)


def _tipos_caso() -> tuple[str, ...]:
    return (
        *("completo",) * 36,
        *("limite_7",) * 4,
        *("separacion_8",) * 3,
        *("faltante",) * 3,
        *("ambiguo",) * 2,
        *("corrupto",) * 2,
    )


def _fechas(tipo_caso: str, base: date) -> dict[str, date]:
    if tipo_caso == "limite_7":
        return {"ecg": base, "laboratorio": base + timedelta(days=7), "ecocardiograma": base + timedelta(days=6)}
    if tipo_caso == "separacion_8":
        return {"ecg": base, "laboratorio": base + timedelta(days=7), "ecocardiograma": base + timedelta(days=8)}
    return {tipo: base for tipo in ("ecg", "laboratorio", "ecocardiograma")}


def _copiar(ruta: Path, entrada: Path, nombre: str) -> Path:
    destino = entrada / nombre
    shutil.copyfile(ruta, destino)
    return destino


def _crear_entrada(
    directorio: Path, semilla: int, tipos_caso: tuple[str, ...], duplicados: int
) -> tuple[Path, int, list[str]]:
    entrada = directorio / "entrada"
    generados = directorio / "generados"
    entrada.mkdir(parents=True)
    valores_pii: list[str] = []
    for indice, tipo_caso in enumerate(tipos_caso):
        prefijo = f"caso-{indice:03d}"
        base = date(2024, 1, 1) + timedelta(days=indice * 20)
        fechas = _fechas(tipo_caso, base)
        corpus = generar_corpus_clinico(
            generados / prefijo, semilla=semilla + indice,
            fechas_estudio=fechas, registrar_pii=valores_pii.extend,
        )
        rutas = {documento.tipo: documento.ruta for documento in corpus.documentos}
        tipos = ("ecg", "laboratorio") if tipo_caso in {"faltante", "corrupto"} else tuple(rutas)
        for tipo in tipos:
            _copiar(rutas[tipo], entrada, f"{prefijo}__{tipo}.pdf")
        if tipo_caso == "ambiguo":
            alterno = generar_corpus_clinico(
                generados / f"{prefijo}-alterno",
                semilla=semilla + indice + 10_000,
                fechas_estudio=fechas,
                registrar_pii=valores_pii.extend,
            )
            laboratorio = next(documento.ruta for documento in alterno.documentos if documento.tipo == "laboratorio")
            _copiar(laboratorio, entrada, f"{prefijo}__laboratorio_b.pdf")
        if tipo_caso == "corrupto":
            corrupto = crear_pdf_corrupto(entrada / f"{prefijo}__ecocardiograma.pdf")
            corrupto.write_bytes(corrupto.read_bytes() + f"-{indice}".encode())
        if indice < duplicados:
            _copiar(rutas["ecg"], entrada, f"zz-duplicado-{indice:03d}.pdf")
    return entrada, sum(1 for _ in entrada.glob("*.pdf")), valores_pii


def _resolver_claves(_identidad, _pepper, _resolutor, *, id_documento: str, etapa: str) -> ClavesPaciente:
    id_caso = id_documento.split("__", maxsplit=1)[0]
    return ClavesPaciente(id_paciente=f"pac-{id_caso}", id_alt_paciente=None, version_clave=1)


def contar_coincidencias_pii(registros: list[object], valores_pii: list[str]) -> int:
    serializados = tuple(repr(registro).casefold() for registro in registros)
    return sum(valor.casefold() in registro for registro in serializados for valor in valores_pii)


def ejecutar_corpus_sintetico(
    directorio: Path, *, semilla: int, tipos_caso: tuple[str, ...], duplicados: int
) -> ResumenPiloto:
    entrada, pdfs_entrada, valores_pii = _crear_entrada(
        directorio, semilla, tipos_caso, duplicados
    )
    inventario = tuple(
        FuenteLocal(
            raices=(directorio,),
            directorio=entrada,
            tope_bytes=10 * 1024 * 1024,
            huellas=HuellasEnMemoria(),
            cuarentena=_CuarentenaMemoria(),
        ).listar()
    )
    items = tuple(ItemLote(Path(artefacto.uri).stem, artefacto) for artefacto in inventario)
    destino = _DestinoMemoria()
    cuarentena = _CuarentenaMemoria()
    reintentos = 0

    def contar_reintento(_segundos: float) -> None:
        nonlocal reintentos
        reintentos += 1

    # El banco pasa por la MISMA raiz de composicion que el trabajador
    # (`construir_fabrica_ejecutor`) y no arma `EjecutorPipeline` a mano. Es
    # deliberado: armarlo por separado fue lo que dejo al banco midiendo un
    # cableado que produccion no usaba -- inyectaba el coordinador de episodios
    # cuando produccion no lo hacia, de modo que sus conteos de cuarentena
    # describian un camino que el trabajador no recorria. Cualquier cableado
    # nuevo que se agregue a la fabrica ahora llega al banco solo.
    #
    # Lo unico que se sobrescribe son los dobles que el banco NECESITA para
    # correr en segundos en vez de horas: un motor de PII offline (el real carga
    # spaCy), una resolucion de claves sintetica, y un `dormir` que cuenta
    # reintentos en lugar de dormirlos. El destino en memoria es igualmente
    # deliberado: el banco mide el pipeline, no la escritura a Postgres.
    ejecutor = construir_fabrica_ejecutor(
        raices=(directorio,),
        resolutor=object(),
        motor=_MotorPiiOffline(),
        pepper=b"pepper-piloto-sintetico",
        destino=destino,
        cuarentena=cuarentena,
        dormir=contar_reintento,
        resolver_claves=_resolver_claves,
    )()
    resultados = ejecutor.procesar_lote(items)
    codigos = Counter(error.codigo.value for error in cuarentena.errores)
    pii_en_salida = contar_coincidencias_pii(destino.registros, valores_pii)
    return ResumenPiloto(
        casos=len(tipos_caso),
        pdfs_entrada=pdfs_entrada,
        documentos_inventariados=len(items),
        episodios_aprobados=len(destino.episodios),
        documentos_publicados=sum(isinstance(resultado, ExitoDocumento) for resultado in resultados),
        documentos_en_cuarentena=len(cuarentena.errores),
        cuarentena_por_codigo=dict(sorted(codigos.items())),
        registros_inspeccionados=len(destino.registros),
        valores_pii_verificados=len(valores_pii),
        pii_en_salida=pii_en_salida,
        reintentos=reintentos,
    )


def ejecutar_corpus_piloto(directorio: Path, *, semilla: int) -> ResumenPiloto:
    return ejecutar_corpus_sintetico(
        directorio, semilla=semilla, tipos_caso=_tipos_caso(), duplicados=5
    )
