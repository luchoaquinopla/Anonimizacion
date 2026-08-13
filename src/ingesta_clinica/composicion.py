"""Composicion de dependencias para la ingesta clinica efimera."""

from ingesta_clinica.adaptadores.salida.laboratorio import AdaptadorFamiliaLaboratorio
from ingesta_clinica.aplicacion.puertos.entrada import PuertoEntradaIngesta


def crear_puerto_entrada_ingesta() -> PuertoEntradaIngesta:
    """Compone el caso de uso con el adaptador de laboratorio en memoria."""
    return PuertoEntradaIngesta(AdaptadorFamiliaLaboratorio())
