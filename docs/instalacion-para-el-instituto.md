# Instalar el panel en una computadora del instituto

Esta guía es para alguien que **no** trabaja con computadoras técnicamente (por ejemplo, un médico que va a usar el panel). No hace falta saber programar ni usar la línea de comandos más allá de copiar y pegar dos comandos.

Si algo de esta guía falla y no sabés qué hacer, **avisá a quien te dio este repositorio** (la persona que mantiene el proyecto) antes de seguir. No sigas adelante "a ver si funciona": cada paso explica qué mirar en pantalla.

## Qué vas a necesitar antes de empezar

- Una computadora con **Windows 10 o superior**.
- **Conexión a internet** (la primera vez -- después no hace falta).
- Que alguien de sistemas (IT) te diga cómo conectarte a la base de datos del instituto, o que ya tengas una base de datos Postgres corriendo (por ejemplo, con Docker Desktop y el archivo `docker-compose.yml` de este mismo repositorio -- si no sabés qué es esto, consultá con IT).

## Paso 1 -- Descargar el proyecto

Si ya tenés esta carpeta en tu computadora (por ejemplo, porque alguien te la copió o la clonaste con Git), pasá directo al Paso 2.

## Paso 2 -- Correr el instalador

1. Abrí el **Explorador de archivos** y entrá a la carpeta del proyecto.
2. Entrá a la carpeta `scripts`.
3. Hacé **clic derecho** sobre el archivo `instalar.ps1` y elegí **"Ejecutar con PowerShell"**.

   Si Windows muestra una pantalla azul que dice "Windows protegió su PC" (esto es normal la primera vez que se ejecuta un script de este repositorio), hacé clic en **"Más información"** y después en **"Ejecutar de todas formas"**.

   Si en cambio aparece un mensaje sobre "directivas de ejecución" (execution policy) y el script no arranca, abrí PowerShell como administrador y pegá este comando una sola vez (autoriza correr scripts firmados o locales, no baja nada de internet):

   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   ```

   y volvé a intentar el clic derecho de arriba.

4. Se va a abrir una ventana negra (la terminal) con texto. **Dejala abierta** hasta que termine -- puede tardar varios minutos la primera vez, porque descarga varios programas de internet.

### Qué tenés que ver si salió bien

La ventana va mostrando pasos numerados del 1 al 7, cada uno con `[OK]` en verde cuando termina. Al final vas a ver algo como:

```
== Paso 7 de 7: verificando que todo haya quedado en orden ==
[OK   ] Pepper: configurado.
[OK   ] Secreto del panel: no configurado (no hace falta -- el panel sólo va a escuchar en esta máquina).
[OK   ] Base de datos: conexión correcta.
[OK   ] Migraciones: al día.
[OK   ] Corrida activa: ninguna -- se puede lanzar una corrida nueva.

Instalacion terminada: todo quedo en orden.
```

Si en cambio ves una línea que dice `[FALTA]`, leé el texto que sigue -- **te dice en español qué falta y qué hacer**. El caso más común es que todavía no haya una base de datos Postgres encendida y accesible: para eso hace falta ayuda de IT (ver `deploy/operacion-institucional.md`), esto no lo resuelve el instalador solo.

### Si el instalador se detiene con `[ERROR]`

Un `[ERROR]` (en rojo) significa que el instalador se frenó antes de terminar -- nunca deja algo a medias en silencio. El texto que sigue a `Que hacer:` dice exactamente qué hacer. Los dos casos más comunes:

- **"No se encontró una instalación de Python..."**: el instalador te va a dar un comando para copiar y pegar (empieza con `winget install ...`). Pegalo en una ventana de PowerShell, esperá a que termine, cerrá esa ventana, abrí una nueva, y volvé a hacer el Paso 2 desde el principio.
- **"No se pudo descargar..."** (el paquete o el modelo): normalmente es un problema de conexión a internet. Revisá la conexión y volvé a correr `instalar.ps1`.

Podés volver a correr `instalar.ps1` las veces que haga falta: no rompe nada si ya corrió antes (no vuelve a generar el pepper ni el secreto del panel si ya existen).

## Paso 3 -- Guardar el secreto del panel (si el instalador lo mostró)

Si es la primera vez que se instala en esta máquina, vas a ver un recuadro amarillo con un texto largo de letras y números, algo así:

```
-----------------------------------------------------------------
 SECRETO DEL PANEL (se muestra UNA sola vez en esta pantalla):
 3f9a2c81b4e0...
-----------------------------------------------------------------
```

**Esto solo hace falta si otra computadora de la red del instituto va a mirar el panel** (no si lo vas a usar solo desde esta misma máquina). Si no estás seguro, guardalo igual en un lugar seguro (un gestor de contraseñas, o un papel guardado bajo llave) por las dudas -- no se vuelve a mostrar en pantalla, aunque queda guardado en un archivo de tu usuario de Windows que el programa sabe leer solo.

## Paso 4 -- Levantar el panel

1. Volvé a la carpeta `scripts`.
2. Hacé doble clic en `iniciar_panel.ps1` (o clic derecho → "Ejecutar con PowerShell", igual que en el Paso 2).
3. Se va a abrir una ventana negra que dice "Levantando el panel de operación..." y, a los pocos segundos, se va a abrir sola una pestaña del navegador con el reporte de cuarentena.

**No cierres la ventana negra** mientras estés usando el panel -- cerrarla apaga el panel. Para apagarlo cuando termines, cerrá esa ventana.

### Consejo: crear un acceso directo

Para no tener que ir a buscar la carpeta `scripts` cada vez:

1. Clic derecho sobre `iniciar_panel.ps1` → **"Crear acceso directo"**.
2. Arrastrá el acceso directo al Escritorio.
3. A partir de ahora, doble clic en ese ícono del Escritorio levanta el panel.

## ¿A quién avisar si algo sale mal?

- Si el instalador (`instalar.ps1`) muestra `[ERROR]` y el mensaje de "Qué hacer" no resuelve el problema: avisá a quien mantiene este repositorio, con una foto o captura de pantalla del mensaje completo.
- Si `anonimizacion diagnosticar` (Paso 7) muestra `[FALTA] Base de datos: ...`: avisá a IT -- necesitan dejar Postgres encendido y accesible desde esta máquina.
- Si el panel se abre pero se ve una página en blanco o un error del navegador: avisá a quien mantiene el repositorio con la dirección exacta que aparece en la barra del navegador.

## Qué NO hace este instalador

- No instala Postgres (la base de datos): eso lo deja a cargo de IT, porque suele ser compartida entre varias máquinas del instituto.
- No instala Python por su cuenta si falta: te da el comando exacto para que lo instales vos (o pidas ayuda), nunca instala software sin avisar.
- No expone el panel a la red del instituto por defecto: por defecto solo funciona en esta misma computadora, la opción de red es aparte y requiere el secreto del panel.
