[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$ProjectDirectory = Split-Path -Parent $PSScriptRoot
$VirtualEnvironment = Join-Path $ProjectDirectory '.venv'
$Python = Join-Path $VirtualEnvironment 'Scripts\python.exe'
$Requirements = Join-Path $ProjectDirectory 'requirements.txt'

if (-not (Test-Path -LiteralPath $Python)) {
    $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Launcher) {
        & $Launcher.Source -3 -m venv $VirtualEnvironment
    } else {
        $Launcher = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $Launcher) { throw 'Python 3 is required.' }
        & $Launcher.Source -m venv $VirtualEnvironment
    }
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

& $Python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed.' }
& $Python -m pip install --upgrade --upgrade-strategy only-if-needed -r $Requirements
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$env:TOOLBOX_PROJECT_DIR = $ProjectDirectory
@'
import os
import sys
from pathlib import Path
import customtkinter
import cryptography
import paramiko
import tkinter
import yaml
from PIL import Image

project = Path(os.environ['TOOLBOX_PROJECT_DIR'])
sys.path.insert(0, str(project))
from execution_engines.main import ExecutionEngine
from execution_engines.settings import load_variables

engine = ExecutionEngine(project)
if 'local_host_training' not in engine.actions:
    raise SystemExit('The local Windows host action is not registered')
for path in (project / 'menus').glob('*.yaml'):
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise SystemExit(f'{path.name}: YAML root must be a mapping')
for required in ('deployment-variables.yaml', 'training-variables.yaml', 'troubleshooting-variables.yaml'):
    if not (project / 'variables' / required).is_file():
        raise SystemExit(f'Missing variable file: {required}')
variable_files = sorted((project / 'variables').rglob('*.yaml'))
for path in variable_files:
    load_variables(path)
print(f'Windows setup validation passed ({len(engine.actions)} actions; {len(variable_files)} variable files and their Includes).')
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'Application validation failed.' }

$LauncherPath = Join-Path $ProjectDirectory 'run_toolbox.ps1'
@'
$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Windows virtual environment not found. Run .\run-once\run-once.ps1 first.'
}
& $Python (Join-Path $PSScriptRoot 'main.py') @args
exit $LASTEXITCODE
'@ | Set-Content -LiteralPath $LauncherPath -Encoding UTF8

$Record = @"
YAML Toolbox Windows setup completed successfully.
Completed: $([DateTime]::Now.ToString('o'))
Python: $(& $Python --version)
Virtual environment: $VirtualEnvironment
Launcher: $(Join-Path $ProjectDirectory 'run_toolbox.ps1')
"@
Set-Content -LiteralPath (Join-Path $ProjectDirectory '.setup-complete') -Value $Record -Encoding UTF8
Write-Output $Record
Write-Output 'Start the application with: .\run_toolbox.ps1'
