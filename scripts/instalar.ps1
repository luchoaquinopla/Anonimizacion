#Requires -Version 5.1
<#
.SINOPSIS
    Instalador del pipeline de anonimizacion para una maquina del instituto.

.DESCRIPCION
    Pensado para que lo corra alguien SIN experiencia tecnica (ver
    docs/instalacion-para-el-instituto.md para las instrucciones completas,
    en lenguaje llano). Hace, en orden:

      1. Verifica que haya Python 3.11 o superior. Si no lo hay, NO lo
         instala solo -- muestra el comando exacto de "winget" y se detiene.
      2. Crea un entorno virtual dedicado (".venv" en la raiz del repositorio).
      3. Instala el paquete "anonimizacion" y sus dependencias ahi adentro.
      4. Descarga el modelo de spaCy que necesita el motor de deteccion de
         datos personales (es_core_news_lg).
      5. Genera (si no existen) el pepper y el secreto del panel, los guarda
         FUERA del repositorio (en el perfil del usuario de Windows, nunca
         versionado) y los deja configurados para las proximas sesiones.
      6. Crea "anonimizacion.toml" a partir del ejemplo, si todavia no existe.
      7. Corre "anonimizacion diagnosticar" y muestra su salida tal cual --
         para que quien instala vea con sus propios ojos si quedo listo.

    DECISION DE DISENO -- por que un script y no un .exe unico:
    El pipeline carga spaCy + Presidio + el modelo "es_core_news_lg"
    (cientos de MB en total). Empaquetar todo eso en un unico ejecutable
    (PyInstaller "--onefile") produce un binario enorme, lento para arrancar
    (tiene que descomprimirse a un directorio temporal cada vez) y fragil
    ante cualquier dependencia nativa que el empaquetador no detecte bien.
    Un entorno virtual + este script de arranque es mas grande en disco,
    pero arranca rapido, es facil de diagnosticar cuando algo falla (los
    mensajes de error apuntan a un archivo .py real, no a un binario
    opaco) y es el mismo mecanismo que ya usa cualquier instalacion de
    Python en un servidor administrado por IT (ver
    deploy/operacion-institucional.md).

    Cada paso falla RUIDOSO: si algo sale mal, el script dice que fallo y
    que hacer, y se detiene ahi -- nunca sigue en silencio con una
    instalacion a medias.

.NOTAS
    Requiere conexion a internet la primera vez (para descargar paquetes de
    Python y el modelo de spaCy). Postgres NO lo instala este script -- ver
    deploy/operacion-institucional.md para dejarlo funcionando (por ejemplo,
    con el "docker-compose.yml" del repositorio si ya hay Docker Desktop).
#>

[CmdletBinding()]
param(
    # Version minima de Python aceptada -- debe coincidir con
    # "requires-python" de pyproject.toml.
    [string]$VersionPythonMinima = "3.11",
    # Nombre del modelo de spaCy que el pipeline necesita (pii/motor.py).
    [string]$ModeloSpacy = "es_core_news_lg"
)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
# Sin esto, los acentos que imprime "anonimizacion diagnosticar" (un proceso
# Python hijo) salen mal codificados en la consola de Windows aunque
# PowerShell ya este en UTF-8 -- PYTHONUTF8 fuerza que Python mismo use UTF-8
# para su entrada/salida estandar, sin depender de la pagina de codigos activa.
$env:PYTHONUTF8 = "1"

$RaizRepo = Split-Path -Parent $PSScriptRoot
$RutaVenv = Join-Path $RaizRepo ".venv"
$RutaVenvPython = Join-Path $RutaVenv "Scripts\python.exe"
$RutaVenvAnonimizacion = Join-Path $RutaVenv "Scripts\anonimizacion.exe"
$CarpetaSecretos = Join-Path $env:LOCALAPPDATA "anonimizacion\secretos"
$RutaPepper = Join-Path $CarpetaSecretos "pepper.txt"
$RutaSecretoPanel = Join-Path $CarpetaSecretos "panel_secreto.txt"
$RutaConfigEjemplo = Join-Path $RaizRepo "deploy\anonimizacion.toml.example"
$RutaConfig = Join-Path $RaizRepo "anonimizacion.toml"

function Write-Paso {
    param([string]$Texto)
    Write-Host ""
    Write-Host "== $Texto ==" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Texto)
    Write-Host "[OK] $Texto" -ForegroundColor Green
}

function Salir-ConError {
    param([string]$Mensaje, [string]$QueHacer)
    Write-Host ""
    Write-Host "[ERROR] $Mensaje" -ForegroundColor Red
    if ($QueHacer) {
        Write-Host "Que hacer: $QueHacer" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "La instalacion se detuvo. Nada quedo corriendo a medias sin avisar." -ForegroundColor Red
    exit 1
}

function Obtener-VersionPython {
    param([string]$RutaEjecutable)
    try {
        $salida = & $RutaEjecutable -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        return $null
    }
    if ($LASTEXITCODE -ne 0 -or -not $salida) { return $null }
    return $salida.Trim()
}

# --- Paso 1: Python compatible ------------------------------------------------

Write-Paso "Paso 1 de 7: buscando Python $VersionPythonMinima o superior"

$PythonEncontrado = $null
$candidatos = @()
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $candidatos += @{ Comando = "py"; Args = @("-3") }
}
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    $candidatos += @{ Comando = "python"; Args = @() }
}

foreach ($candidato in $candidatos) {
    $ejecutable = (Get-Command $candidato.Comando -ErrorAction SilentlyContinue).Source
    if (-not $ejecutable) { continue }
    $version = Obtener-VersionPython -RutaEjecutable $ejecutable
    if (-not $version) { continue }
    $partes = $version.Split(".")
    $minimaPartes = $VersionPythonMinima.Split(".")
    $cumple = ([int]$partes[0] -gt [int]$minimaPartes[0]) -or `
        ([int]$partes[0] -eq [int]$minimaPartes[0] -and [int]$partes[1] -ge [int]$minimaPartes[1])
    if ($cumple) {
        $PythonEncontrado = $ejecutable
        Write-Ok "Se encontro Python $version en: $ejecutable"
        break
    }
}

if (-not $PythonEncontrado) {
    Salir-ConError `
        -Mensaje "No se encontro una instalacion de Python $VersionPythonMinima o superior en esta maquina." `
        -QueHacer @"
Instalar Python desde una terminal (PowerShell) con este comando exacto, y despues volver a correr este instalador:

    winget install --id Python.Python.3.11 -e

Si "winget" no esta disponible, descargar Python desde https://www.python.org/downloads/ (marcar la casilla "Add python.exe to PATH" durante la instalacion) y volver a abrir una terminal nueva antes de reintentar.
"@
}

# --- Paso 2: entorno virtual dedicado -----------------------------------------

Write-Paso "Paso 2 de 7: preparando el entorno dedicado ($RutaVenv)"

if (Test-Path $RutaVenvPython) {
    Write-Ok "Ya existe un entorno dedicado -- se reutiliza sin recrearlo."
} else {
    & $PythonEncontrado -m venv $RutaVenv
    if ($LASTEXITCODE -ne 0) {
        Salir-ConError -Mensaje "No se pudo crear el entorno virtual en '$RutaVenv'." `
            -QueHacer "Verificar espacio libre en disco y permisos de escritura en esa carpeta, y reintentar."
    }
    Write-Ok "Entorno dedicado creado."
}

# --- Paso 3: instalar el paquete y sus dependencias ---------------------------

Write-Paso "Paso 3 de 7: instalando el programa y sus dependencias (puede tardar varios minutos)"

& $RutaVenvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) {
    Salir-ConError -Mensaje "No se pudo actualizar pip dentro del entorno dedicado." `
        -QueHacer "Verificar conexion a internet y reintentar. Si el problema persiste, avisar a quien mantiene el repositorio."
}

& $RutaVenvPython -m pip install --editable $RaizRepo
if ($LASTEXITCODE -ne 0) {
    Salir-ConError -Mensaje "No se pudo instalar el paquete 'anonimizacion' y sus dependencias." `
        -QueHacer "Revisar el mensaje de pip de arriba (suele ser falta de conexion a internet, o un paquete que necesita compilarse y falta una herramienta del sistema). Reintentar despues de resolverlo."
}
Write-Ok "Paquete y dependencias instalados."

# --- Paso 4: modelo de spaCy ---------------------------------------------------

Write-Paso "Paso 4 de 7: descargando el modelo de deteccion de datos personales ($ModeloSpacy, puede tardar varios minutos)"

& $RutaVenvPython -m spacy download $ModeloSpacy
if ($LASTEXITCODE -ne 0) {
    Salir-ConError -Mensaje "No se pudo descargar el modelo de spaCy '$ModeloSpacy'." `
        -QueHacer "Verificar conexion a internet y reintentar. Sin este modelo el pipeline NO puede detectar nombres de pacientes -- no continuar sin resolverlo."
}
Write-Ok "Modelo de spaCy listo."

# --- Paso 5: secretos (pepper y secreto del panel) ----------------------------

Write-Paso "Paso 5 de 7: configurando los secretos del pipeline"

function Generar-SecretoHex {
    param([int]$Bytes = 32)
    $buffer = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
    -join ($buffer | ForEach-Object { $_.ToString("x2") })
}

New-Item -ItemType Directory -Path $CarpetaSecretos -Force | Out-Null

$secretoPanelGenerado = $false
if (Test-Path $RutaPepper) {
    Write-Ok "Ya existe un pepper en '$RutaPepper' -- se conserva sin tocar (regenerarlo invalidaria todos los identificadores de paciente ya generados)."
} else {
    Set-Content -Path $RutaPepper -Value (Generar-SecretoHex) -NoNewline -Encoding ascii
    Write-Ok "Pepper nuevo generado y guardado en '$RutaPepper'."
}

if (Test-Path $RutaSecretoPanel) {
    Write-Ok "Ya existe un secreto del panel en '$RutaSecretoPanel' -- se conserva sin tocar."
} else {
    $secretoPanelValor = Generar-SecretoHex
    Set-Content -Path $RutaSecretoPanel -Value $secretoPanelValor -NoNewline -Encoding ascii
    $secretoPanelGenerado = $true
    Write-Ok "Secreto del panel nuevo generado y guardado en '$RutaSecretoPanel'."
}

# El PEPPER es persistente para el USUARIO de Windows actual (sobrevive a
# reiniciar la terminal y la maquina) -- ademas, seteado en ESTE proceso para
# que "anonimizacion diagnosticar" (paso 7) lo vea sin abrir una terminal
# nueva. Hace falta SIEMPRE, tenga o no red el panel.
[Environment]::SetEnvironmentVariable("ANONIMIZACION_PEPPER_ARCHIVO", $RutaPepper, "User")
$env:ANONIMIZACION_PEPPER_ARCHIVO = $RutaPepper

# El secreto del PANEL, deliberadamente, NO se activa por defecto (ni acá ni
# en "scripts\iniciar_panel.ps1"): "anonimizacion servir" sin
# "--escuchar-red" funciona SIN pedir contrasena mientras el panel sólo
# escuche en esta máquina (deploy/anonimizacion.toml.example, "sin necesidad
# de secreto") -- eso es a proposito, para el caso mas comun (un solo
# operador, una sola maquina). Si se activara acá, el panel empezaría a
# pedir Basic Auth incluso en localhost, rompiendo ese modo sin fricción.
# El archivo YA QUEDA LISTO Y GENERADO para el día que haga falta exponerlo
# a la red: "scripts\iniciar_panel.ps1 -EscucharRed" lo activa recién en ese
# momento.

if ($secretoPanelGenerado) {
    $valorMostrado = Get-Content -Path $RutaSecretoPanel -Raw
    Write-Host ""
    Write-Host "-----------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host " SECRETO DEL PANEL (se muestra UNA sola vez en esta pantalla):" -ForegroundColor Yellow
    Write-Host " $valorMostrado" -ForegroundColor Yellow
    Write-Host "-----------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host " Guardalo en un lugar seguro (por ejemplo, un gestor de" -ForegroundColor Yellow
    Write-Host " contrasenas). Hace falta para entrar al panel SOLO si otra" -ForegroundColor Yellow
    Write-Host " computadora de la red va a mirarlo (--escuchar-red); si el" -ForegroundColor Yellow
    Write-Host " panel se usa solo desde esta misma maquina, no hace falta" -ForegroundColor Yellow
    Write-Host " escribirlo en ningun lado. Ya quedo guardado tambien en:" -ForegroundColor Yellow
    Write-Host " $RutaSecretoPanel" -ForegroundColor Yellow
    Write-Host "-----------------------------------------------------------------" -ForegroundColor Yellow
}

# --- Paso 6: archivo de configuracion (sin secretos) --------------------------

Write-Paso "Paso 6 de 7: preparando el archivo de configuracion"

if (Test-Path $RutaConfig) {
    Write-Ok "Ya existe '$RutaConfig' -- se conserva sin tocar."
} else {
    Copy-Item -Path $RutaConfigEjemplo -Destination $RutaConfig
    Write-Ok "Se creo '$RutaConfig' a partir del ejemplo. Revisar 'raiz' y 'db_url' antes de procesar PDFs reales."
}

# --- Paso 7: diagnostico final -------------------------------------------------

Write-Paso "Paso 7 de 7: verificando que todo haya quedado en orden"

Push-Location $RaizRepo
try {
    & $RutaVenvAnonimizacion diagnosticar
    $codigoDiagnostico = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Host ""
if ($codigoDiagnostico -eq 0) {
    Write-Host "Instalacion terminada: todo quedo en orden." -ForegroundColor Green
} else {
    Write-Host "Instalacion terminada, PERO 'anonimizacion diagnosticar' encontro algo pendiente (ver [FALTA] arriba)." -ForegroundColor Yellow
    Write-Host "Cada linea [FALTA] explica que falta y como resolverlo -- lo mas comun es que falte" -ForegroundColor Yellow
    Write-Host "Postgres encendido (ver deploy/operacion-institucional.md)." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Para levantar el panel de operacion: scripts\iniciar_panel.ps1" -ForegroundColor Cyan

exit $codigoDiagnostico
