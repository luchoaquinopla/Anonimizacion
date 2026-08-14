## Verificación

**Comando ejecutado**
- `.venv/Scripts/python.exe -m pytest`
- Resultado: **15 passed in 0.05s**
- `tests/test_triangulacion_resolucion_campos.py`: **6 passed**

**Hallazgos**
- Sin bloqueantes ni defectos detectados.
- `tests/test_triangulacion_resolucion_campos.py` cubre:
  - unidad incompatible → `malformado`
  - valor malformado y truncado
  - múltiples candidatos → `ambiguo`
  - ausencia opcional → `no_presente`, sin bloquear
  - estado explícito para cada campo del inventario
- `src/ingesta_clinica/dominio/extraccion.py` conserva únicamente códigos, estados, indicadores booleanos y procedencia técnica; no modela valores clínicos ni texto fuente.
- No hay infraestructura fuera de alcance en los dos archivos inspeccionados.

**Riesgo residual**
- Revisión limitada deliberadamente a los dos archivos autorizados; no se inspeccionó el resto del repositorio ni se ejecutó medición de cobertura.