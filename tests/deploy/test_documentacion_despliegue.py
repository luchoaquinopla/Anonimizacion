from __future__ import annotations

from pathlib import Path


def test_documentacion_de_despliegue_cubre_operacion_y_secretos() -> None:
    raiz = Path(__file__).parents[2]
    operacion = (raiz / "deploy" / "operacion-institucional.md").read_text(encoding="utf-8")
    variables = (raiz / "deploy" / "variables-entorno.example").read_text(encoding="utf-8")
    readme = (raiz / "README.md").read_text(encoding="utf-8")

    for termino in ("permisos", "backup", "retención", "rollback", "TLS", "cuarentena"):
        assert termino.lower() in operacion.lower()
    for variable in ("ANONIMIZACION_PEPPER", "ANONIMIZACION_PANEL_SECRETO", "ANONIMIZACION_DB_URL"):
        assert variable in variables
    assert "CELERY_" not in operacion
    assert "CELERY_" not in variables
    assert "no contiene secretos" in variables.lower()
    assert "deploy/operacion-institucional.md" in readme
