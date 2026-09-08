#Requires -Version 5.1
<#
.SINOPSIS
    Levanta el panel de operacion y abre el navegador en la pantalla correcta.

.DESCRIPCION
    Pensado para doblehacer clic (o un acceso directo que apunte a este
    archivo) despues de haber corrido "scripts\instalar.ps1" una vez.

    Corre "anonimizacion servir" en esta misma ventana (dejarla abierta
    mientras se usa el panel) y abre el navegador por defecto en
    "http://127.0.0.1:<puerto>/cuarentena" -- el reporte de documentos
    apartados, la unica pantalla que no depende de conocer de antemano el
    identificador de una corrida puntual. Para ver el progreso de una
    corrida especifica, agregar "/panel/<id-de-la-corrida>" a la barra de
    direcciones (el identificador lo devuelve "anonimizacion procesar", o la
    respuesta de crear una corrida desde el panel).

    Por defecto el panel SOLO escucha en esta maquina (nadie mas en la red
    del instituto puede verlo) -- ver deploy/operacion-institucional.md
    antes de exponerlo con "--escuchar-red".
#>

[CmdletBinding()]
param(
    [switch]$EscucharRed
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONUTF8 = "1"

$RaizRepo = Split-Path -Parent $PSScriptRoot
$RutaVenvAnonimizacion = Join-Path $RaizRepo ".venv\Scripts\anonimizacion.exe"
$RutaConfig = Join-Path $RaizRepo "anonimizacion.toml"
$CarpetaSecretos = Join-Path $env:LOCALAPPDATA "anonimizacion\secretos"
$RutaPepper = Join-Path $CarpetaSecretos "pepper.txt"
$RutaSecretoPanel = Join-Path $CarpetaSecretos "panel_secreto.txt"

if (-not (Test-Path $RutaVenvAnonimizacion)) {
    Write-Host "[ERROR] No se encontro el entorno instalado en '$RaizRepo\.venv'." -ForegroundColor Red
    Write-Host "Que hacer: correr primero 'scripts\instalar.ps1' desde esta misma carpeta." -ForegroundColor Yellow
    exit 1
}

# "scripts\instalar.ps1" persiste ANONIMIZACION_PEPPER_ARCHIVO a nivel de
# USUARIO de Windows, pero esa variable solo llega a procesos NUEVOS despues
# de que Windows propague el cambio -- un doble clic hecho desde una sesion
# de Explorer que ya estaba abierta ANTES de instalar puede no verla
# todavia. En vez de depender de esa propagacion, este lanzador apunta
# directo a la ruta conocida si la variable no llego -- mismo archivo que
# escribe el instalador, nunca un valor inventado. El pepper hace falta
# SIEMPRE (con o sin red).
if (-not $env:ANONIMIZACION_PEPPER_ARCHIVO -and (Test-Path $RutaPepper)) {
    $env:ANONIMIZACION_PEPPER_ARCHIVO = $RutaPepper
}

# El secreto del panel, en cambio, sólo se activa con "-EscucharRed": sin
# red, "anonimizacion servir" funciona sin pedir contraseña mientras el
# panel sólo escuche en esta máquina -- activarlo siempre convertiría el uso
# local sin red en un panel que pide Basic Auth sin necesidad (ver el mismo
# comentario en "scripts\instalar.ps1").
if ($EscucharRed) {
    if (-not (Test-Path $RutaSecretoPanel)) {
        Write-Host "[ERROR] No se encontro el secreto del panel en '$RutaSecretoPanel'." -ForegroundColor Red
        Write-Host "Que hacer: correr 'scripts\instalar.ps1' de nuevo -- genera este archivo la primera vez." -ForegroundColor Yellow
        exit 1
    }
    if (-not $env:ANONIMIZACION_PANEL_SECRETO_ARCHIVO) {
        $env:ANONIMIZACION_PANEL_SECRETO_ARCHIVO = $RutaSecretoPanel
    }
    Write-Host "Exponiendo el panel a la red del instituto -- va a pedir el secreto del panel (contrasena) a quien lo abra." -ForegroundColor Yellow
    Write-Host "El secreto guardado en '$RutaSecretoPanel' es el que 'scripts\instalar.ps1' mostro una sola vez al instalar." -ForegroundColor Yellow
}

# Puerto: leido del archivo de configuracion si existe, si no el default del
# propio programa (8000, ver configuracion.py). Se usa solo para saber que
# direccion abrir en el navegador -- "anonimizacion servir" vuelve a leer el
# mismo archivo por su cuenta.
$Puerto = 8000
if (Test-Path $RutaConfig) {
    $lineaPuerto = Select-String -Path $RutaConfig -Pattern '^\s*puerto\s*=\s*(\d+)' -ErrorAction SilentlyContinue
    if ($lineaPuerto) {
        $Puerto = [int]$lineaPuerto.Matches[0].Groups[1].Value
    }
}

Push-Location $RaizRepo
try {
    Write-Host "Levantando el panel de operacion (puerto $Puerto)..." -ForegroundColor Cyan
    Write-Host "Dejar esta ventana abierta mientras se use el panel. Cerrarla corta el panel." -ForegroundColor Yellow

    $argumentos = @("servir")
    if ($EscucharRed) { $argumentos += "--escuchar-red" }

    $proceso = Start-Process -FilePath $RutaVenvAnonimizacion -ArgumentList $argumentos -PassThru -NoNewWindow

    # Le da al servidor un instante para levantar el socket antes de abrir el
    # navegador -- si igual no llego a tiempo, el navegador solo muestra "no
    # se puede acceder" un momento y el usuario puede refrescar la pagina.
    Start-Sleep -Seconds 2

    Start-Process "http://127.0.0.1:$Puerto/cuarentena"

    Wait-Process -Id $proceso.Id
} finally {
    Pop-Location
}
