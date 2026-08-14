## Verificación

- **Sin bloqueantes:** `entrada.py` depende únicamente de `PuertoSalidaClasificacionFamilia`, definido como `Protocol` en `aplicacion/puertos/salida.py`.
- **Arquitectura correcta:** la aplicación no importa `AdaptadorFamiliaLaboratorio`.
- **Cableado concreto aislado:** `AdaptadorFamiliaLaboratorio` se instancia únicamente en `src/ingesta_clinica/composicion.py`.
- **Adaptador orientado al puerto:** `adaptadores/salida/laboratorio.py` devuelve `ResultadoClasificacionFamilia`, definido por la capa de aplicación.
- **Pruebas:** 16 pasaron.
- **Riesgo bajo:** no hay una prueba estructural que impida futuras importaciones del adaptador desde aplicación.
- **Problema de alcance menor:** la ruta solicitada `aplicacion/composicion.py` no existe; la composición está correctamente ubicada en `ingesta_clinica/composicion.py`.
- No edité archivos. Estado de staging y diff real no verificados porque no se autorizó ejecutar comandos Git.