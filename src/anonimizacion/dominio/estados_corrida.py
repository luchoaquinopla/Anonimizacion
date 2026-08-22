from __future__ import annotations

from enum import Enum


class EstadoCorrida(str, Enum):
    CREADA = "creada"
    INVENTARIANDO = "inventariando"
    PROCESANDO = "procesando"
    RECONCILIANDO = "reconciliando"
    PUBLICANDO = "publicando"
    COMPLETADA = "completada"
    COMPLETADA_CON_CUARENTENA = "completada_con_cuarentena"
    FALLIDA = "fallida"


class EstadoDocumentoCorrida(str, Enum):
    INVENTARIADO = "inventariado"
    CLASIFICADO = "clasificado"
    EXTRAIDO_MINIMO = "extraido_minimo"
    ASOCIADO = "asociado"
    EXTRAIDO_COMPLETO = "extraido_completo"
    RECONCILIADO = "reconciliado"
    APROBADO = "aprobado"
    CUARENTENA = "cuarentena"
    ERROR_RECUPERABLE = "error_recuperable"
    ERROR_FINAL = "error_final"
