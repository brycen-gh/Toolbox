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
}

& $Python -m pip install --upgrade pip
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

engine = ExecutionEngine(project)
if 'local_host_training' not in engine.actions:
    raise SystemExit('The local Windows host action is not registered')
for path in (project / 'menus').glob('*.yaml'):
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict):
        raise SystemExit(f'{path.name}: YAML root must be a mapping')
print(f'Windows setup validation passed ({len(engine.actions)} registered actions).')
'@ | & $Python -
if ($LASTEXITCODE -ne 0) { throw 'Application validation failed.' }

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
