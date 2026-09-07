"""Dobles de módulo (picklables) para `tests/trabajadores/test_despacho_paralelo.py`.

Tienen que vivir en un módulo real e importable, no como closures/lambdas
dentro del test: `ProcessPoolExecutor` con `spawn` (default en Windows)
pickla las funciones sometidas por referencia de módulo -- ver el docstring
de `anonimizacion.trabajadores.despacho_paralelo` para la verificación
empírica de por qué un closure o una función de un módulo no resoluble
rompe el pool en vez de fallar la tarea puntual.
"""

from __future__ import annotations

import os
from pathlib import Path

# Variable de entorno (no un argumento de la función): permite pasar un
# directorio de marcadores al hijo vía la MISMA herencia de entorno que usa
# el pepper real (`obtener_pepper`) -- exactamente lo que este cambio
# verificó que funciona con `spawn`. Un argumento explícito forzaría cambiar
# la firma de `funcion_trabajo` (fijada por `despacho_paralelo.FuncionTrabajo`)
# solo para un detalle de instrumentación de test.
VAR_ENV_MARCADOR = "_ANONIMIZACION_TEST_MARCADOR_DESPACHO"
#: Mismo convenio, para el centinela de pereza (MEDIO 6, revisión
#: adversarial): un directorio donde cada tarea completada deja un archivo
#: ANTES de retornar -- permite que el generador de grupos, corriendo en el
#: proceso padre, observe si YA hubo alguna completación en el momento
#: exacto en que se le pide el siguiente grupo.
VAR_ENV_MARCADOR_COMPLETADOS = "_ANONIMIZACION_TEST_MARCADOR_COMPLETADOS"

ID_DOCUMENTO_QUE_MUERE_SIEMPRE = "doc-que-muere-siempre"


def trabajo_devuelve_pid(corrida_id: str, grupo) -> list[dict[str, object]]:
    """Doble mínimo: no hace nada del pipeline real, solo confirma en qué PID corrió."""
    pid = os.getpid()
    return [{"id_documento": referencia["id_documento"], "estado": "exito", "pid": pid} for referencia in grupo]


def trabajo_muere_siempre_si_esta_marcado(corrida_id: str, grupo) -> list[dict[str, object]]:
    """Muere en TODO intento (nunca se recupera) si el grupo contiene el
    documento centinela `ID_DOCUMENTO_QUE_MUERE_SIEMPRE` -- para probar el
    camino de "reintentos agotados, grupo dado por perdido, la corrida
    sigue"."""
    if any(referencia["id_documento"] == ID_DOCUMENTO_QUE_MUERE_SIEMPRE for referencia in grupo):
        os._exit(137)  # simula un OOM-kill del SO: sin excepcion, sin traceback pickleable
    return [{"id_documento": referencia["id_documento"], "estado": "exito"} for referencia in grupo]


def trabajo_muere_la_primera_vez_por_grupo(corrida_id: str, grupo) -> list[dict[str, object]]:
    """Muere SOLO en el primer intento de cada grupo (identificado por el
    `id_documento` de su primera referencia); en el reintento, con un
    proceso hijo nuevo, tiene éxito -- para probar el camino de recuperación
    automática ante `BrokenProcessPool`."""
    directorio_marcador = Path(os.environ[VAR_ENV_MARCADOR])
    id_grupo = grupo[0]["id_documento"]
    archivo_marcador = directorio_marcador / f"intento-{id_grupo}"
    if not archivo_marcador.exists():
        archivo_marcador.touch()
        os._exit(137)
    return [{"id_documento": referencia["id_documento"], "estado": "exito"} for referencia in grupo]


def trabajo_marca_completado_y_devuelve_pid(corrida_id: str, grupo) -> list[dict[str, object]]:
    """Como `trabajo_devuelve_pid`, pero deja un archivo en
    `VAR_ENV_MARCADOR_COMPLETADOS` ANTES de retornar -- el orden importa: el
    marcador queda escrito antes de que `future.result()` pueda desbloquear
    al padre, así que si el padre lo ve, es porque esta tarea genuinamente
    terminó, no una carrera."""
    directorio = Path(os.environ[VAR_ENV_MARCADOR_COMPLETADOS])
    resultado = [
        {"id_documento": referencia["id_documento"], "estado": "exito", "pid": os.getpid()} for referencia in grupo
    ]
    (directorio / f"listo-{grupo[0]['id_documento']}").touch()
    return resultado


class CuarentenaEnMemoria:
    """Doble de `pipeline.ejecutor.DestinoCuarentena` -- sin Postgres."""

    def __init__(self) -> None:
        self.errores: list[object] = []

    def registrar(self, error: object) -> None:
        self.errores.append(error)


def referencia(id_documento: str) -> dict[str, str]:
    return {"id_documento": id_documento, "uri": f"/fake/{id_documento}.pdf", "sha256": f"sha-{id_documento}"}
