"""Renderiza el reporte de cuarentena como HTML, sin dependencias.

Por qué HTML servido y no una aplicación de página única: este panel corre en la
máquina del instituto, donde el pipeline es 100 % offline. Un framework con paso
de compilación agrega fricción de instalación y una superficie de red que el
proyecto no quiere, para una pantalla que no la necesita. Todo el CSS va en línea
por la misma razón --- no hay red de la que traer una hoja de estilos.

Sobre la forma: para un puñado de números titulares la forma correcta es una fila
de fichas más una tabla, no un gráfico de barras. Tres categorías no justifican
ejes.

Sobre el color: se usa la paleta de ESTADO, que es fija y no temática. En
superficie clara dos de sus pasos quedan por debajo de 3:1 de contraste a
propósito, y la mitigación es que el color NUNCA viaja solo: cada grupo lleva
símbolo y etiqueta. El texto usa tokens de tinta, nunca el color del estado.
"""

from __future__ import annotations

from html import escape

from .reporte_cuarentena import GrupoDeAccion, ReporteCuarentena

_ESTILOS = """
:root {
  --superficie: #fcfcfb;
  --plano: #f9f9f7;
  --tinta: #0b0b0b;
  --tinta-secundaria: #52514e;
  --tinta-tenue: #898781;
  --linea: #e1e0d9;
  --borde: rgba(11, 11, 11, 0.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --superficie: #1a1a19;
    --plano: #0d0d0d;
    --tinta: #ffffff;
    --tinta-secundaria: #c3c2b7;
    --tinta-tenue: #898781;
    --linea: #2c2c2a;
    --borde: rgba(255, 255, 255, 0.10);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 32px 24px 64px;
  background: var(--plano);
  color: var(--tinta);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1040px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
.subtitulo { color: var(--tinta-secundaria); margin: 0 0 28px; }
.fichas { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
.ficha {
  background: var(--superficie);
  border: 1px solid var(--borde);
  border-radius: 10px;
  padding: 16px 18px;
}
.ficha-encabezado { display: flex; align-items: center; gap: 8px; }
.simbolo { font-size: 13px; line-height: 1; }
.ficha-titulo { font-weight: 600; font-size: 14px; }
.ficha-total { font-size: 34px; font-weight: 650; margin: 10px 0 2px; letter-spacing: -0.02em; }
.ficha-nota { color: var(--tinta-secundaria); font-size: 13px; margin: 0; }
.ficha-accion { color: var(--tinta); font-size: 13px; margin: 10px 0 0; }
section { margin-top: 36px; }
h2 { font-size: 16px; margin: 0 0 2px; display: flex; align-items: center; gap: 8px; }
.seccion-nota { color: var(--tinta-secundaria); font-size: 13px; margin: 0 0 12px; }
.tabla-envoltorio { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; background: var(--superficie); }
caption { text-align: left; color: var(--tinta-tenue); font-size: 13px; padding: 0 0 8px; }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--linea); vertical-align: top; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--tinta-tenue); font-weight: 600; }
td.identificador { font-family: ui-monospace, "Cascadia Code", Consolas, monospace; font-size: 12px; color: var(--tinta-secundaria); }
.vacio { background: var(--superficie); border: 1px solid var(--borde); border-radius: 10px; padding: 28px; text-align: center; color: var(--tinta-secundaria); }
"""


def _ficha(grupo: GrupoDeAccion) -> str:
    presentacion = grupo.presentacion
    return f"""
    <article class="ficha">
      <div class="ficha-encabezado">
        <span class="simbolo" style="color: {presentacion.color}" aria-hidden="true">{presentacion.simbolo}</span>
        <span class="ficha-titulo">{escape(presentacion.titulo)}</span>
      </div>
      <p class="ficha-total">{grupo.total}</p>
      <p class="ficha-nota">{escape(presentacion.que_significa)}</p>
      <p class="ficha-accion"><strong>Qué hacer:</strong> {escape(presentacion.que_hacer)}</p>
    </article>"""


def _seccion(grupo: GrupoDeAccion) -> str:
    presentacion = grupo.presentacion
    filas = "\n".join(
        f"""        <tr>
          <td class="identificador">{escape(detalle.id_documento)}</td>
          <td>{escape(detalle.tipo_documento or "sin identificar")}</td>
          <td>{escape(detalle.explicacion)}</td>
          <td>{escape(detalle.ubicacion or "—")}</td>
        </tr>"""
        for detalle in grupo.detalles
    )
    return f"""
    <section>
      <h2>
        <span class="simbolo" style="color: {presentacion.color}" aria-hidden="true">{presentacion.simbolo}</span>
        {escape(presentacion.titulo)}
      </h2>
      <p class="seccion-nota">{escape(presentacion.que_hacer)}</p>
      <div class="tabla-envoltorio">
        <table>
          <caption>{grupo.total} estudio(s) apartado(s)</caption>
          <thead>
            <tr><th>Identificador</th><th>Tipo</th><th>Motivo</th><th>Dónde</th></tr>
          </thead>
          <tbody>
{filas}
          </tbody>
        </table>
      </div>
    </section>"""


def renderizar_reporte(reporte: ReporteCuarentena) -> str:
    """Devuelve la página completa. No recibe nada más que el reporte."""
    grupos = reporte.grupos_con_casos

    if not grupos:
        cuerpo = (
            '<div class="vacio">No hay estudios apartados. '
            "Todos los documentos procesados pasaron las verificaciones.</div>"
        )
    else:
        cuerpo = (
            f'<div class="fichas">{"".join(_ficha(grupo) for grupo in grupos)}</div>'
            f'{"".join(_seccion(grupo) for grupo in grupos)}'
        )

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estudios apartados para revisión</title>
<style>{_ESTILOS}</style>
</head>
<body>
<main>
  <h1>Estudios apartados para revisión</h1>
  <p class="subtitulo">{reporte.total} en total, agrupados por lo que hay que hacer con cada uno.</p>
  {cuerpo}
</main>
</body>
</html>"""
