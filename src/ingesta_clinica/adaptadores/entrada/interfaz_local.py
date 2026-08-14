"""Marcado de una pantalla local que no muestra datos de archivos."""


def html_interfaz_local() -> str:
    """Devuelve una pantalla estática para abrir localmente en un navegador."""
    return """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>Carga local</title></head>
<body>
  <main>
    <h1>Carga local</h1>
    <label for="archivos">Arrastre archivos PDF o selecciónelos aquí</label>
    <input id="archivos" type="file" accept="application/pdf" multiple>
    <section id="drop" aria-label="Área de arrastre">Suelte los PDF aquí</section>
    <p id="acuse" aria-live="polite">El acuse aparece al terminar el lote.</p>
  </main>
  <script>
    const input = document.querySelector('#archivos');
    const zona = document.querySelector('#drop');
    zona.addEventListener('dragover', (evento) => evento.preventDefault());
    zona.addEventListener('drop', (evento) => {
      evento.preventDefault();
      input.files = evento.dataTransfer.files;
    });
  </script>
</body>
</html>"""
