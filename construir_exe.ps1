param([switch]$Clean)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

$Requirements = Join-Path $Root "requirements.txt"
$BuildRequirements = Join-Path $Root "requirements-build.txt"
$ConfigFile = Join-Path $Root "configuracion\filtros.json"
$NodeExecutable = "C:\Program Files\nodejs\node.exe"

if (!(Test-Path $NodeExecutable)) {
    throw "Node.js executable required for Playwright packaging."
}


if (!(Test-Path $Requirements)) {
    throw "Missing requirements.txt"
}

if (!(Test-Path $BuildRequirements)) {
    throw "Missing requirements-build.txt"
}

if (!(Test-Path $ConfigFile)) {
    throw "Missing default filtering configuration."
}

# ------------------------------------------
# 1. Locate Python on the BUILD computer
# ------------------------------------------

if (!(Test-Path $Python)) {

    Write-Host "`n=== CREATING BUILD ENVIRONMENT ==="

    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue

    if ($PyLauncher) {
        $PyPath = $PyLauncher.Source
        & $PyPath -3 -m venv $Venv
    }
    else {
        $PythonCommand = Get-Command python -ErrorAction SilentlyContinue

        if (!$PythonCommand) {
            throw "Python 3 is required on the build computer."
        }

        & $PythonCommand.Source -m venv $Venv
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Virtual environment creation failed."
    }
}

if (!(Test-Path $Python)) {
    throw "Virtual environment Python was not created."
}

# ------------------------------------------
# 2. Install application dependencies
# ------------------------------------------

Write-Host "`n=== UPDATING PIP ==="

& $Python -m pip install --upgrade pip

if ($LASTEXITCODE -ne 0) {
    throw "pip update failed."
}

Write-Host "`n=== INSTALLING APPLICATION REQUIREMENTS ==="

& $Python -m pip install -r $Requirements

if ($LASTEXITCODE -ne 0) {
    throw "Application dependency installation failed."
}

Write-Host "`n=== INSTALLING BUILD REQUIREMENTS ==="

& $Python -m pip install -r $BuildRequirements

if ($LASTEXITCODE -ne 0) {
    throw "Build dependency installation failed."
}

# ------------------------------------------
# 3. Run the complete test suite
# ------------------------------------------

Write-Host "`n=== RUNNING COMPLETE TEST SUITE ==="

& $Python -m compileall -q aplicacion

if ($LASTEXITCODE -ne 0) {
    throw "Python compilation failed."
}

& $Python -m py_compile iniciar_filtro.py

if ($LASTEXITCODE -ne 0) {
    throw "Launcher compilation failed."
}
# Run only canonical test modules; preserve historical backups.
$TestScript = "import subprocess,sys; r=subprocess.run([sys.executable,'-W','ignore::ResourceWarning','-m','unittest','discover','-s','tests','-q'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace'); lines=r.stdout.splitlines(); print('\n'.join(x for x in lines if x.startswith(('Ran ','OK (','FAILED'))) if r.returncode==0 else '\n'.join(lines[-45:])); sys.exit(r.returncode)"
& $Python -B -c $TestScript
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. Executable build cancelled."
}

if ($LASTEXITCODE -ne 0) {
    throw "Tests failed. Executable build cancelled."
}

# ------------------------------------------
# 4. Optional clean build
# ------------------------------------------

if ($Clean) {
    Remove-Item (Join-Path $Root "build") `
        -Recurse -Force -ErrorAction SilentlyContinue

    Remove-Item (Join-Path $Root "dist") `
        -Recurse -Force -ErrorAction SilentlyContinue
}

# ------------------------------------------
# 5. Build standalone executable
# ------------------------------------------

Write-Host "`n=== BUILDING EXECUTABLE ==="

$CategoryDirectory = Join-Path $Root "Filtro"
$RequiredCategoryFiles = @(
    "catalogo_oficial_completo.json",
    "categorias_exclusion_total.txt",
    "categorias_exclusion_pasiva.txt"
)

foreach ($Name in $RequiredCategoryFiles) {
    $File = Join-Path $CategoryDirectory $Name
    if (!(Test-Path -LiteralPath $File -PathType Leaf)) {
        throw "Missing category configuration: $Name"
    }
}

$BundledData = "$ConfigFile;configuracion"

$OcrModel = Join-Path $Root "datos\adjuntos\tessdata\spa.traineddata"
if (!(Test-Path -LiteralPath $OcrModel -PathType Leaf)) {
    throw "Missing Spanish OCR model: $OcrModel"
}
$BundledOcrData = "$OcrModel;datos\adjuntos\tessdata"
$AttachmentCode = Join-Path $Root "integracion_adjuntos\codigo"
$LegacyDocHelper = Join-Path $AttachmentCode "extractor_doc_legacy.ps1"

$AttachmentModules = @(
    "bloqueo_instancia",
    "checkpoint_descargas",
    "coordinador_limpieza",
    "coordinador_produccion",
    "descargador_individual",
    "extractor_excel",
    "extractor_pdf",
    "extractor_produccion",
    "extractor_word",
    "lotes_produccion",
    "mp_windows_cleanup",
    "navegador_adjuntos",
    "orquestador_produccion",
    "seleccion_incluidas"
)

foreach ($Module in $AttachmentModules) {
    if (!(Test-Path -LiteralPath (Join-Path $AttachmentCode "$Module.py") -PathType Leaf)) {
        throw "Missing production attachment module: $Module"
    }
}

if (!(Test-Path -LiteralPath $LegacyDocHelper -PathType Leaf)) {
    throw "Missing legacy Word extraction helper."
}

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "Iniciar_Filtro" `
    --paths $AttachmentCode `
    --collect-all playwright `
    --collect-all keyring `
    --collect-all win32ctypes `
    --hidden-import keyring.backends.Windows `
    --hidden-import bloqueo_instancia `
    --hidden-import checkpoint_descargas `
    --hidden-import coordinador_limpieza `
    --hidden-import coordinador_produccion `
    --hidden-import descargador_individual `
    --hidden-import extractor_excel `
    --hidden-import extractor_pdf `
    --hidden-import extractor_produccion `
    --hidden-import extractor_word `
    --hidden-import lotes_produccion `
    --hidden-import mp_windows_cleanup `
    --hidden-import navegador_adjuntos `
    --hidden-import orquestador_produccion `
    --hidden-import adaptador_montos_api_filtro_2 `
    --hidden-import coordinador_filtro_2 `
    --hidden-import estado_filtro_2 `
    --hidden-import evaluador_filtro_2 `
    --hidden-import integrador_filtro_2 `
    --hidden-import interprete_filtro_2 `
    --hidden-import pipeline_filtro_2 `
    --hidden-import registro_filtro_2 `
    --hidden-import validador_filtro_2 `
    --hidden-import workspace_diario `
    --hidden-import seleccion_incluidas `
    --add-binary "$NodeExecutable;." `
    --add-data $BundledData `
    --add-data $BundledOcrData `
    --add-data "$LegacyDocHelper;." `
    "iniciar_filtro.py"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

# ------------------------------------------
# 6. Verify and publish executable
# ------------------------------------------

$BuiltExe = Join-Path $Root "dist\Iniciar_Filtro.exe"
$RootExe = Join-Path $Root "Iniciar_Filtro.exe"

if (!(Test-Path $BuiltExe)) {
    throw "Expected executable was not created."
}
$DistCategoryDirectory = Join-Path $Root "dist\Filtro"
New-Item -ItemType Directory -Path $DistCategoryDirectory -Force | Out-Null

foreach ($Name in $RequiredCategoryFiles) {
    Copy-Item (Join-Path $CategoryDirectory $Name) $DistCategoryDirectory -Force
    if (!(Test-Path (Join-Path $DistCategoryDirectory $Name) -PathType Leaf)) {
        throw "Category packaging verification failed: $Name"
    }
}


if (!(Test-Path -LiteralPath $BuiltExe -PathType Leaf)) {
    throw "Build artifact missing."
}

$BuiltInfo = Get-Item -LiteralPath $BuiltExe
if ($BuiltInfo.Length -le 0) {
    throw "Build artifact is empty."
}

Write-Host "`n======================================"
Write-Host "BUILD ARTIFACT READY"
Write-Host "Production executable: NOT MODIFIED"
Write-Host "Publication: DEFERRED UNTIL VERIFICATION"
Write-Host "======================================"
