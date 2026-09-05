"""Renderiza el panel de operación como HTML, sin dependencias (Tramo 5).

Mismo criterio de forma que `plantilla_reporte.py`: para un puñado de cifras
titulares la forma correcta es fichas más tabla, no un gráfico -- siete
etapas no justifican ejes. El embudo por etapa se dibuja como barras
proporcionales en HTML/CSS puro dentro de la tabla, nunca con una biblioteca
de gráficos.

Mismo criterio de color: la paleta de ESTADO es la de `reporte_cuarentena.py`
(fija, no temática) -- los mismos cuatro valores, sin agregar ninguno nuevo.
En superficie clara, dos de sus pasos quedan por debajo de 3:1 de contraste a
propósito; la mitigación obligatoria es que el color NUNCA viaja solo: cada
estado lleva también símbolo (`aria-hidden="true"`, decorativo) y etiqueta en
texto. El texto usa tokens de tinta, nunca el color del estado.

La diferencia central con el reporte de cuarentena: ACÁ el `<script>` es un
requisito, no un accidente. Una corrida dura horas; el operador no debería
tener que recargar la página para ver el avance. El polling va **en línea**
(cero `<script src>`, cero URLs absolutas) y escribe con **`textContent`**,
nunca `innerHTML` -- así la página no puede convertirse en vector de
inyección ni aunque un código de cuarentena llegara con marcado, sin
necesidad de escapar del lado del cliente porque nada se interpreta como
HTML. El primer pintado ya trae los números calculados por el servidor: la
pantalla es útil antes de que corra un solo `fetch`, y sigue siendo legible
si el JavaScript está deshabilitado.

Se rotula por lo que la persona necesita entender, no por el nombre de la
variable (mismo criterio que `reporte_cuarentena.py` aplicó a los códigos de
cuarentena): `residuo` es el nombre del campo en el JSON -- lo consumen
programas --, pero en pantalla se llama "En proceso", con una nota que
explica qué significa. Lo mismo para "Apartados": lleva una nota que dice
que requieren revisión y linkea al reporte de cuarentena.

Un residuo negativo (design.md, Decisión 9) nunca se muestra como un cero:
se dibuja como su propia ficha de descuadre, con símbolo, etiqueta y
explicación -- el cierre visual del residuo con signo que calcula
`embudo_corrida.py`. Las fichas "En proceso" y "Descuadre" son mutuamente
excluyentes según `cierra`; la que no aplica queda **oculta con CSS**
(`display: none`), no omitida del marcado -- decisión deliberada, no un
descuido: ningún dato sensible viaja ahí (son conteos administrativos, ya
derivados de tablas sin PII), y mantener el nodo listo en el DOM permite que
el `<script>` alterne su visibilidad con un simple cambio de `style` más
`textContent`, sin depender de `innerHTML` para crear elementos nuevos si un
refresco posterior cambia de estado.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from html import escape
from typing import Any

_ETIQUETA_ETAPA: dict[str, str] = {
    "ingesta": "Ingesta",
    "extraccion": "Extracción",
    "parseo": "Parseo",
    "reconciliacion": "Reconciliación",
    "coordinacion": "Coordinación",
    "pseudonimizacion": "Pseudonimización",
    "salida": "Salida",
}

# Los mismos cuatro valores de `reporte_cuarentena.PRESENTACION` -- no se
# agrega ningún color nuevo. Se repiten acá (en vez de importarse) porque
# esa paleta describe ACCIONES sobre cuarentena, y ésta describe la MARCHA
# de una corrida: son dominios distintos que comparten la misma paleta fija
# de estado, no el mismo vocabulario.
_COLOR_NEUTRO = "#898781"  # SIN_CLASIFICAR
_COLOR_ADVERTENCIA = "#fab219"  # PEDIR_MATERIAL
_COLOR_CRITICO = "#d03b3b"  # REVISAR_A_MANO

#: marcha -> (color, símbolo decorativo, etiqueta en texto)
_PRESENTACION_MARCHA: dict[str, tuple[str, str, str]] = {
    "completa": (_COLOR_NEUTRO, "●", "Completa"),
    "en_vuelo": (_COLOR_NEUTRO, "◐", "En vuelo"),
    "sin_avance": (_COLOR_ADVERTENCIA, "▲", "Sin avance"),
    "descuadre": (_COLOR_CRITICO, "■", "Descuadre"),
}

_EXPLICACION_DESCUADRE = (
    "hay documentos con más de un desenlace registrado: un reprocesamiento "
    "duplicado, o una escritura de salida que quedó a medias"
)

_ESTILOS = """
:root {
  --superficie: #fcfcfb;
  --plano: #f9f9f7;
  --tinta: #0b0b0b;
  --tinta-secundaria: #52514e;
  --tinta-tenue: #898781;
  --linea: #e1e0d9;
  --borde: rgba(11, 11, 11, 0.10);
  --barra-fondo: rgba(11, 11, 11, 0.08);
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
    --barra-fondo: rgba(255, 255, 255, 0.10);
  }
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  /* La página nunca se desplaza horizontalmente: el contenido ancho (la
     tabla del embudo) lleva su propio scroll en `.tabla-envoltorio`. */
  overflow-x: hidden;
}
body {
  padding: 32px 24px 64px;
  background: var(--plano);
  color: var(--tinta);
  font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 1040px; margin: 0 auto; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: -0.01em; }
.subtitulo { color: var(--tinta-secundaria); margin: 0 0 28px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.fichas { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
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
.ficha-nota { color: var(--tinta-secundaria); font-size: 13px; margin: 8px 0 0; }
.ficha-nota a { color: inherit; }
.ficha-descuadre { border-color: var(--borde); }
section { margin-top: 36px; }
h2 { font-size: 16px; margin: 0 0 2px; }
.seccion-nota { color: var(--tinta-secundaria); font-size: 13px; margin: 0 0 12px; }
.tabla-envoltorio { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 640px; background: var(--superficie); }
th, td { text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--linea); vertical-align: middle; }
th { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--tinta-tenue); font-weight: 600; }
td.numero { font-variant-numeric: tabular-nums; white-space: nowrap; }
.barra-envoltorio { background: var(--barra-fondo); border-radius: 4px; height: 8px; width: 160px; overflow: hidden; }
.barra { background: var(--tinta-tenue); height: 100%; }
.estimacion { color: var(--tinta-secundaria); }
.actualizado { color: var(--tinta-tenue); font-size: 12px; margin-top: 8px; }
"""


def _color_y_etiqueta_marcha(marcha: str) -> tuple[str, str, str]:
    return _PRESENTACION_MARCHA.get(marcha, (_COLOR_NEUTRO, "?", escape(marcha)))


def _formatear_seg(segundos: object) -> str:
    total = int(segundos or 0)
    horas, resto = divmod(total, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def _texto_estimacion(estimacion: Mapping[str, Any]) -> str:
    situacion = estimacion.get("situacion")
    if situacion == "disponible":
        minimo = _formatear_seg(estimacion.get("restante_seg_min"))
        maximo = _formatear_seg(estimacion.get("restante_seg_max"))
        return f"Entre {minimo} y {maximo}"
    if situacion == "midiendo":
        return "Midiendo"
    if situacion == "sin_avance":
        return "Sin avance en los últimos 5 minutos"
    if situacion == "descuadre":
        return "Descuadre: no se puede estimar"
    return "Sin información"


def _ficha(titulo: str, valor: object, id_valor: str, nota: str | None = None) -> str:
    nota_html = f'\n      <p class="ficha-nota">{nota}</p>' if nota else ""
    return f"""
    <article class="ficha">
      <p class="ficha-titulo">{escape(titulo)}</p>
      <p class="ficha-total" id="{id_valor}">{escape(str(valor))}</p>{nota_html}
    </article>"""


def _ficha_marcha(marcha: str) -> str:
    color, simbolo, etiqueta = _color_y_etiqueta_marcha(marcha)
    return f"""
    <article class="ficha">
      <div class="ficha-encabezado">
        <span class="simbolo" style="color: {color}" aria-hidden="true">{simbolo}</span>
        <span class="ficha-titulo">Marcha</span>
      </div>
      <p class="ficha-total" id="valor-marcha" data-marcha="{escape(marcha)}">{etiqueta}</p>
    </article>"""


def _ficha_en_proceso(residuo: int, *, visible: bool) -> str:
    """"En proceso", no "Residuo": ese es el nombre de la VARIABLE, no algo
    que la persona que mira la pantalla pueda interpretar sola. El nombre
    técnico sigue viviendo en el JSON (`residuo`), que consumen programas.

    Mutuamente excluyente con `_ficha_descuadre` según `cierra` -- ver el
    docstring del módulo sobre por qué la que no aplica queda oculta con CSS
    en vez de omitida del marcado.
    """
    estilo = "" if visible else ' style="display: none"'
    return f"""
    <article class="ficha" id="ficha-en-proceso"{estilo}>
      <p class="ficha-titulo">En proceso</p>
      <p class="ficha-total" id="valor-residuo">{residuo}</p>
      <p class="ficha-nota">
        Documentos que ya entraron a la corrida y todavía no tienen un desenlace registrado
        (ni publicados ni apartados).
      </p>
    </article>"""


def _ficha_descuadre(residuo: int, *, visible: bool) -> str:
    """La ficha propia del descuadre (design.md, Decisión 9). Nunca un cero.

    Mutuamente excluyente con `_ficha_en_proceso` según `cierra` -- ver el
    docstring del módulo sobre por qué la que no aplica queda oculta con CSS
    en vez de omitida del marcado.
    """
    color, simbolo, _etiqueta = _PRESENTACION_MARCHA["descuadre"]
    cantidad = abs(residuo)
    estilo = "" if visible else ' style="display: none"'
    return f"""
    <article class="ficha ficha-descuadre" id="ficha-descuadre"{estilo}>
      <div class="ficha-encabezado">
        <span class="simbolo" style="color: {color}" aria-hidden="true">{simbolo}</span>
        <span class="ficha-titulo">Descuadre</span>
      </div>
      <p class="ficha-total" id="valor-descuadre-total">{cantidad}</p>
      <p class="ficha-nota" id="valor-descuadre-texto">
        Descuadre: {cantidad} documentos con más de un desenlace. {escape(_EXPLICACION_DESCUADRE)}.
      </p>
    </article>"""


def _fila_etapa(etapa: Mapping[str, Any], max_apartados: int) -> str:
    """La barra mide la PÉRDIDA relativa a la peor etapa, no `llegaron /
    entraron`. Con una corrida a mitad de camino, `llegaron / entraron` da
    prácticamente el mismo número (~la mitad) en las siete etapas: siete
    barras casi idénticas no comunican nada, y sugieren que no hay pérdida
    en ningún punto cuando sí la hay. La pregunta que la pantalla tiene que
    responder es DÓNDE se caen los documentos -- eso varía por etapa, y esta
    barra lo hace visible de un vistazo: la fila con más apartados es la
    barra más larga.
    """
    nombre = str(etapa["etapa"])
    etiqueta = _ETIQUETA_ETAPA.get(nombre, nombre)
    llegaron = int(etapa["llegaron"])
    apartados = int(etapa["apartados"])
    porcentaje = 0.0 if max_apartados <= 0 else min(100.0, (apartados / max_apartados) * 100)
    codigos = etapa.get("codigos") or {}
    detalle_codigos = ", ".join(f"{escape(str(codigo))}: {cantidad}" for codigo, cantidad in codigos.items())
    return f"""
        <tr>
          <td>{escape(etiqueta)}</td>
          <td class="numero" id="etapa-{escape(nombre)}-llegaron">{llegaron}</td>
          <td class="numero" id="etapa-{escape(nombre)}-apartados">{apartados}</td>
          <td>{detalle_codigos or "—"}</td>
          <td>
            <div class="barra-envoltorio">
              <div class="barra" id="etapa-{escape(nombre)}-barra" style="width: {porcentaje:.1f}%"></div>
            </div>
          </td>
        </tr>"""


def _json_para_script(valor: object) -> str:
    """`json.dumps` + escapar `</` como `<\\/`.

    `json.dumps` es correcto para el contexto de un LITERAL de JavaScript
    (comillas, barras invertidas, unicode), pero el contexto real acá es un
    elemento HTML `<script>...</script>`, y `json.dumps` no sabe nada de
    ese contexto: no escapa la secuencia `</`. Un valor que contuviera
    `</script>` cerraría la etiqueta real en medio del literal, y el resto
    del `<script>` legítimo quedaría afuera, interpretado como HTML plano.

    Hoy `corrida_id` siempre es un `uuid4()` (`LanzadorCorrida.lanzar`) y la
    ruta rechaza cualquier identificador con `/` antes de llegar al render
    (`rutas_corridas._panel_corrida`), así que esta secuencia nunca aparece
    en la práctica -- pero esa es una protección INCIDENTAL de otro módulo,
    no defensa propia de esta plantilla. Si el día de mañana se reusa esta
    función desde una ruta sin ese filtro, la plantilla se defiende sola.
    """
    return json.dumps(valor).replace("</", "<\\/")


def _script_polling(corrida_id: str) -> str:
    """El polling en línea (Requisito 7 de la spec, design.md "El punto de entrada").

    Los valores dinámicos se embeben con `_json_para_script` -- no con
    `escape()` -- porque el contexto acá es un literal de JavaScript dentro
    de un elemento `<script>` HTML, no un atributo HTML; `json.dumps` cubre
    el escape de JavaScript (comillas, barras invertidas), y el `</` extra
    cubre el escape del contexto `<script>` que `json.dumps` no conoce (ver
    `_json_para_script`).

    Refresco vía `fetch`/`setInterval`, todo relativo (`/corridas/...`): cero
    `http://`, cero `https://`, cero `<script src>`. Cada valor dinámico se
    escribe con `element.textContent`, nunca con `innerHTML` -- el motivo
    exacto por el que no hace falta escapar nada del lado del cliente.
    """
    corrida_id_js = _json_para_script(corrida_id)
    explicacion_js = _json_para_script(_EXPLICACION_DESCUADRE)
    return f"""
<script>
(function () {{
  var corridaId = {corrida_id_js};
  var explicacionDescuadre = {explicacion_js};
  var ultimaActualizacionMs = Date.now();

  function establecer(id, valor) {{
    var elemento = document.getElementById(id);
    if (elemento) {{
      elemento.textContent = valor;
    }}
  }}

  function actualizarLeyenda() {{
    var segundos = Math.round((Date.now() - ultimaActualizacionMs) / 1000);
    establecer("actualizado-hace", "Actualizado hace " + segundos + " s");
  }}

  function pintar(datos) {{
    establecer("valor-entraron", datos.entraron);
    establecer("valor-publicados", datos.publicados);
    establecer("valor-apartados", datos.apartados);
    establecer("valor-estado", datos.estado);
    establecer("valor-marcha", datos.marcha);

    // "En proceso" y "Descuadre" son mutuamente excluyentes según `cierra`
    // (ver el docstring del módulo): la ficha vigente se muestra y se
    // actualiza, la otra se oculta -- ambas ya existen en el DOM desde el
    // primer pintado, así que alternar es sólo un cambio de `style`.
    var fichaEnProceso = document.getElementById("ficha-en-proceso");
    var fichaDescuadre = document.getElementById("ficha-descuadre");
    if (datos.cierra) {{
      if (fichaDescuadre) {{ fichaDescuadre.style.display = "none"; }}
      if (fichaEnProceso) {{
        fichaEnProceso.style.display = "";
        establecer("valor-residuo", datos.residuo);
      }}
    }} else {{
      if (fichaEnProceso) {{ fichaEnProceso.style.display = "none"; }}
      if (fichaDescuadre) {{
        fichaDescuadre.style.display = "";
        var cantidad = Math.abs(datos.residuo);
        establecer("valor-descuadre-total", cantidad);
        establecer(
          "valor-descuadre-texto",
          "Descuadre: " + cantidad + " documentos con más de un desenlace. " + explicacionDescuadre + "."
        );
      }}
    }}

    var maxApartados = 0;
    (datos.etapas || []).forEach(function (etapa) {{
      if (etapa.apartados > maxApartados) {{ maxApartados = etapa.apartados; }}
    }});
    (datos.etapas || []).forEach(function (etapa) {{
      establecer("etapa-" + etapa.etapa + "-llegaron", etapa.llegaron);
      establecer("etapa-" + etapa.etapa + "-apartados", etapa.apartados);
      var barra = document.getElementById("etapa-" + etapa.etapa + "-barra");
      if (barra) {{
        var porcentaje = maxApartados > 0 ? Math.min(100, (etapa.apartados / maxApartados) * 100) : 0;
        barra.style.width = porcentaje + "%";
      }}
    }});

    // El throughput es una tasa observada, no una promesa: mostrarla junto a
    // "no se puede estimar" (situación "descuadre") contradice ese mensaje,
    // así que la línea entera se oculta mientras dure el descuadre.
    var lineaThroughput = document.getElementById("linea-throughput");
    if (lineaThroughput) {{
      var situacion = datos.estimacion && datos.estimacion.situacion;
      if (situacion === "descuadre") {{
        lineaThroughput.style.display = "none";
      }} else {{
        lineaThroughput.style.display = "";
        if (datos.throughput_por_hora) {{
          establecer("valor-throughput-optimista", datos.throughput_por_hora.optimista);
          establecer("valor-throughput-pesimista", datos.throughput_por_hora.pesimista);
        }}
      }}
    }}

    ultimaActualizacionMs = Date.now();
    actualizarLeyenda();
  }}

  function refrescar() {{
    fetch("/corridas/" + corridaId + "/embudo")
      .then(function (respuesta) {{ return respuesta.json(); }})
      .then(pintar)
      .catch(function () {{
        // Un fetch fallido no borra los números ya pintados (design.md,
        // "La pantalla y su polling"): sólo se actualiza la leyenda de
        // antigüedad, para que se note que el dato ya no es fresco.
        actualizarLeyenda();
      }});
  }}

  setInterval(refrescar, 2000);
  setInterval(actualizarLeyenda, 1000);
  refrescar();
}})();
</script>"""


def renderizar_panel(payload: Mapping[str, Any]) -> str:
    """Devuelve la página completa a partir del contrato JSON del embudo.

    `payload` tiene exactamente la forma que sirve `GET
    /corridas/{id}/embudo` (`servicio_corridas.construir_payload_embudo`):
    reusar la misma forma para el primer pintado y para cada refresco es lo
    que garantiza que la página sea útil ANTES de que corra un solo `fetch`
    (design.md, "La pantalla y su polling").
    """
    corrida_id = str(payload["corrida_id"])
    etapas: Sequence[Mapping[str, Any]] = payload.get("etapas") or []
    cierra = bool(payload["cierra"])
    residuo = int(payload["residuo"])
    throughput = payload.get("throughput_por_hora") or {}
    estimacion = payload.get("estimacion") or {}
    texto_estimacion = _texto_estimacion(estimacion)

    # "En proceso" (`cierra=true`) y "Descuadre" (`cierra=false`) son
    # mutuamente excluyentes: la que no aplica queda oculta con CSS, no
    # omitida -- ver el docstring del módulo.
    ficha_en_proceso = _ficha_en_proceso(residuo, visible=cierra)
    ficha_descuadre = _ficha_descuadre(residuo, visible=not cierra)

    max_apartados = max((int(etapa["apartados"]) for etapa in etapas), default=0)
    filas_etapas = "\n".join(_fila_etapa(etapa, max_apartados) for etapa in etapas)

    # El throughput es una tasa OBSERVADA, no una promesa de tiempo restante:
    # mostrarla junto a "no se puede estimar" (situación "descuadre")
    # contradice ese mensaje. Se oculta la línea entera mientras dure el
    # descuadre, y el `<script>` hace lo mismo en cada refresco.
    situacion = estimacion.get("situacion")
    estilo_throughput = "" if situacion != "descuadre" else ' style="display: none"'

    cuerpo = f"""
  <div class="fichas">
    {_ficha("Entraron", payload["entraron"], "valor-entraron")}
    {_ficha(
        "Publicados",
        payload["publicados"],
        "valor-publicados",
        nota="Documentos que ya salieron con su desenlace completo.",
    )}
    {_ficha(
        "Apartados",
        payload["apartados"],
        "valor-apartados",
        nota='Requieren revisión -- ver el <a href="/cuarentena">reporte de cuarentena</a>.',
    )}
    {ficha_en_proceso}
    {_ficha_marcha(str(payload["marcha"]))}
    {ficha_descuadre}
  </div>
  <section>
    <h2>Embudo por etapa</h2>
    <p class="seccion-nota">La barra mide dónde se pierden más documentos: la etapa con más
      apartados es la barra más larga, no una fracción del total.</p>
    <div class="tabla-envoltorio">
      <table>
        <thead>
          <tr><th>Etapa</th><th>Llegaron</th><th>Apartados</th><th>Motivos</th><th>Pérdida relativa</th></tr>
        </thead>
        <tbody>
{filas_etapas}
        </tbody>
      </table>
    </div>
  </section>
  <section>
    <h2>Tiempo restante</h2>
    <p class="estimacion">{escape(texto_estimacion)}</p>
    <p class="estimacion" id="linea-throughput"{estilo_throughput}>
      Throughput por hora -- optimista: <span id="valor-throughput-optimista">{throughput.get("optimista", 0)}</span>,
      pesimista: <span id="valor-throughput-pesimista">{throughput.get("pesimista", 0)}</span>
    </p>
    <p class="actualizado" id="actualizado-hace">Actualizado recién</p>
  </section>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Panel de operación -- corrida {escape(corrida_id)}</title>
<style>{_ESTILOS}</style>
</head>
<body>
<main>
  <h1>Panel de operación</h1>
  <p class="subtitulo">
    Corrida <span id="valor-corrida-id">{escape(corrida_id)}</span> --
    estado <span id="valor-estado">{escape(str(payload["estado"]))}</span>
  </p>
  {cuerpo}
</main>
{_script_polling(corrida_id)}
</body>
</html>"""
