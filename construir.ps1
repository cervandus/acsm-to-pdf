# Construye las dos versiones portátiles de «ACSM a PDF»:
#   PÚBLICA  ..\7_PUBLICACION EN GITHUB\ACSM-to-PDF-<ver>-windows-portable.zip   SIN carpeta datos (para Releases)
#   PERSONAL ..\6_APP DEFINITIVA\ACSM a PDF\  +  ACSM a PDF <ver> portable.zip    CON tu autorización de Adobe
#            ..\6_APP DEFINITIVA\REGISTRO DE CAMBIOS.txt
$ErrorActionPreference = 'Stop'
$aqui    = $PSScriptRoot
$destino = Join-Path (Split-Path $aqui) '6_APP DEFINITIVA'
$publica = Join-Path (Split-Path $aqui) '7_PUBLICACION EN GITHUB'
$py      = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
$version = ([regex]::Match((Get-Content "$aqui\app.py" -Raw), "VERSION = '([^']+)'")).Groups[1].Value
$obra    = "$env:LOCALAPPDATA\acsm2pdf_build"   # carpeta de trabajo, se reutiliza entre compilaciones
$app     = "$obra\portable\ACSM a PDF"           # salida de PyInstaller + calibre + datos

function Paso($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

Paso "Versión $version"
Get-Process 'ACSM a PDF' -ErrorAction SilentlyContinue | Stop-Process
& $py "$aqui\crear_icono.py"

Paso 'Compilando con PyInstaller'
# el código de terceros se importa con sys.path: hay que decirle a PyInstaller qué módulos son y qué usan
$terceros = Get-ChildItem "$aqui\terceros\deacsm\*.py", "$aqui\terceros\dedrm\*.py" | ForEach-Object { '--hidden-import'; $_.BaseName }
& $py -m PyInstaller --noconfirm --clean --windowed --onedir --log-level WARN `
    --name 'ACSM a PDF' --icon "$aqui\icono.ico" `
    --add-data "$aqui\ui;ui" --add-data "$aqui\terceros;terceros" --add-data "$aqui\icono.ico;." `
    --paths "$aqui\terceros\deacsm" --paths "$aqui\terceros\dedrm" @terceros `
    --collect-all Crypto --collect-all oscrypto --collect-all asn1crypto --hidden-import lxml.etree `
    --distpath "$obra\dist" --workpath "$obra\work" --specpath $obra "$aqui\app.py"
if ($LASTEXITCODE) { throw 'PyInstaller ha fallado' }

Paso 'Montando la carpeta portátil'
# PyInstaller no puede limpiar los archivos de solo lectura de Calibre, por eso Calibre va aparte
robocopy "$obra\dist\ACSM a PDF" $app /MIR /XD calibre datos /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'robocopy ha fallado montando la app' }

Paso 'Copiando Calibre dentro de la app'
robocopy 'C:\Program Files\Calibre2' "$app\calibre" /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'robocopy ha fallado copiando Calibre' }

Copy-Item "$aqui\LEEME.txt", "$aqui\REGISTRO DE CAMBIOS.txt" $app

Paso 'Versión PÚBLICA (para GitHub): sin la carpeta datos'
Remove-Item "$app\datos" -Recurse -Force -ErrorAction SilentlyContinue
if (Test-Path "$app\datos") { throw 'No se ha podido vaciar datos: la versión pública llevaría una autorización' }
New-Item -ItemType Directory -Force $publica | Out-Null
$zipPub = "$publica\ACSM-to-PDF-$version-windows-portable.zip"
Remove-Item $zipPub -ErrorAction SilentlyContinue
Push-Location "$obra\portable"
tar -a -c -f $zipPub --exclude 'ACSM a PDF/datos' 'ACSM a PDF'
Pop-Location
if (-not (Test-Path $zipPub)) { throw 'No se ha creado el .zip público' }
if ((tar -t -f $zipPub) -match '/datos/') { throw 'El .zip público contiene la carpeta datos' }
'{0}  ({1:N0} MB)' -f $zipPub, ((Get-Item $zipPub).Length / 1MB)

Paso 'Versión PERSONAL: copiando tu autorización de Adobe a datos\cuenta adobe'
$p = Start-Process "$app\ACSM a PDF.exe" -ArgumentList '--importar-adobe' -Wait -PassThru
if (-not (Test-Path "$app\datos\cuenta adobe\activation.xml")) { throw 'No se ha podido copiar la autorización de Adobe' }

Paso "Dejando el resultado en $destino"
New-Item -ItemType Directory -Force $destino | Out-Null
# los ajustes que ya tuviera la copia anterior se conservan
$ajustes = "$destino\ACSM a PDF\datos\ajustes.json"
if (Test-Path $ajustes) { Copy-Item $ajustes "$app\datos\ajustes.json" }
robocopy $app "$destino\ACSM a PDF" /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'robocopy ha fallado copiando la app' }
Copy-Item "$aqui\REGISTRO DE CAMBIOS.txt" $destino -Force

Paso 'Creando el .zip'
$zip = "$destino\ACSM a PDF $version portable.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Push-Location $destino
tar -a -c -f $zip 'ACSM a PDF'
Pop-Location
if (-not (Test-Path $zip)) { throw 'No se ha creado el .zip' }

Paso 'Hecho'
'{0}  ({1:N0} MB)' -f $zip, ((Get-Item $zip).Length / 1MB)
