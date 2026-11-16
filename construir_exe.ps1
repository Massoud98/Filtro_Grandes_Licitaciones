param([switch]$Clean)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Venv = Join-Path $Root ".venv"
$Python = Join-Path $Venv "Scripts\python.exe"

$Requirements = Join-Path $Root "requirements.txt"
$BuildRequirements = Join-Path $Root "requirements-build.txt"
$ConfigFile = Join-Path $Root "configuracion\filtros.json"

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
$TestRunner = @'
import re
import sys
import unittest
from pathlib import Path

test_dir = Path("tests")
active = sorted(
    path for path in test_dir.glob("test_*.py")
    if re.fullmatch(r"test_[a-zA-Z0-9_]+\.py", path.name)
)

if len(active) != 26:
    raise SystemExit("STOP: Unexpected active test module count.")

loader = unittest.TestLoader()
suite = unittest.TestSuite(
    loader.loadTestsFromName(f"tests.{path.stem}")
    for path in active
)

if suite.countTestCases() != 248:
    raise SystemExit("STOP: Unexpected active test count.")

result = unittest.TextTestRunner(verbosity=1).run(suite)

if not result.wasSuccessful() or result.skipped:
    raise SystemExit("STOP: Active regression failed.")

print("All 248 active tests passed.")
'@
$TestRunner | & $Python -B -c "import sys; exec(sys.stdin.read())"

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

$BundledData = "$ConfigFile;configuracion"

& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --console `
    --name "Iniciar_Filtro" `
    --collect-all keyring `
    --collect-all win32ctypes `
    --hidden-import keyring.backends.Windows `
    --add-data $BundledData `
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

$BackupDirectory = Join-Path $Root "respaldos"

New-Item -ItemType Directory `
    -Path $BackupDirectory -Force | Out-Null

if (Test-Path $RootExe) {

    $Stamp = Get-Date -Format "yyyyMMdd_HHmmss"

    Copy-Item $RootExe (
        Join-Path $BackupDirectory "Iniciar_Filtro_$Stamp.exe"
    )

    Write-Host "Previous executable preserved."
}

Copy-Item $BuiltExe $RootExe -Force

if (!(Test-Path $RootExe)) {
    throw "Published executable verification failed."
}

Write-Host "`n======================================"
Write-Host "BUILD APPROVED"
Write-Host "======================================"
Write-Host "Executable: $RootExe"
Write-Host "Data directory: Documents\Filtro_Grandes_Licitaciones"
Write-Host "Python required on target: NO"
Write-Host "======================================"