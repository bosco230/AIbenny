param(
    [string]$Root = 'C:\AI-Girlfriend\openmimicry-main\openmimicry-main',
    [string]$BackupRoot = 'C:\AI-Girlfriend\Benny-Backups'
)
$ErrorActionPreference = 'Stop'
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$dest = Join-Path $BackupRoot "Benny-Stable-$stamp"
$projectDest = Join-Path $dest 'project'
$memoryDest = Join-Path $dest 'memory'
New-Item -ItemType Directory -Force -Path $projectDest,$memoryDest | Out-Null
if (-not (Test-Path (Join-Path $Root 'Benny-Launcher.ps1'))) { throw "Project root not found: $Root" }
$log = Join-Path $dest 'backup.log'
$excludedDirs = @('.venv','venv','node_modules','target','.git','.next','dist','build','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','.turbo','.cache')
$excludeFiles = @('*.pyc','*.pyo','*.log','*.tmp')
$robocopyArgs = @($Root,$projectDest,'/E','/R:1','/W:1','/XJ','/NP','/TEE',"/LOG:$log",'/XD') + $excludedDirs + @('/XF') + $excludeFiles
Write-Host "Backing up project to $dest" -ForegroundColor Cyan
& robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) { throw "Robocopy failed with exit code $LASTEXITCODE. See $log" }
$memoryPath = Join-Path $env:USERPROFILE '.openmimicry\memory\memory.sqlite3'
if (Test-Path $memoryPath) {
    $python = Join-Path $Root '.venv\Scripts\python.exe'
    if (-not (Test-Path $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
    $dbDest = Join-Path $memoryDest 'memory.sqlite3'
    $code = @'
import sqlite3, sys
src, dst = sys.argv[1:3]
with sqlite3.connect('file:' + src.replace('\\','/') + '?mode=ro', uri=True, timeout=30) as source:
    with sqlite3.connect(dst) as target:
        source.backup(target)
with sqlite3.connect(dst) as db:
    result = db.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok': raise RuntimeError('SQLite integrity check failed: ' + result)
print('SQLite memory backup verified')
'@
    & $python -c $code $memoryPath $dbDest
    if ($LASTEXITCODE -ne 0) { throw 'SQLite backup failed' }
} else { Write-Warning "Memory database not found: $memoryPath" }
$manifest = [ordered]@{
    created = (Get-Date).ToString('o')
    source_root = $Root
    memory_source = $memoryPath
    excluded_directories = $excludedDirs
    note = 'Source/data backup, not a runnable offline system image. Treat as sensitive: may contain API keys and chat history.'
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $dest 'manifest.json') -Encoding UTF8
Write-Host "BACKUP COMPLETE: $dest" -ForegroundColor Green
