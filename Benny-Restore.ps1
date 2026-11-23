param(
    [Parameter(Mandatory=$true)][string]$BackupPath,
    [string]$RestoreRoot = 'C:\AI-Girlfriend\Benny-Restored'
)
$ErrorActionPreference = 'Stop'
$project = Join-Path $BackupPath 'project'
$memory = Join-Path $BackupPath 'memory\memory.sqlite3'
if (-not (Test-Path $project)) { throw "Backup project folder not found: $project" }
if (Test-Path $RestoreRoot) { throw "Restore destination already exists: $RestoreRoot. Choose a new empty path." }
New-Item -ItemType Directory -Path $RestoreRoot -Force | Out-Null
& robocopy $project $RestoreRoot /E /R:1 /W:1 /XJ /NP
if ($LASTEXITCODE -ge 8) { throw "Project restore failed (robocopy $LASTEXITCODE)" }
if (Test-Path $memory) {
    $safeMemory = Join-Path (Split-Path $RestoreRoot -Parent) ((Split-Path $RestoreRoot -Leaf) + '-memory.sqlite3')
    Copy-Item $memory $safeMemory -ErrorAction Stop
    Write-Host "Memory restored to separate safe file: $safeMemory" -ForegroundColor Yellow
    Write-Host 'Memory NOT overwritten in the live profile. Stop Benny and verify before manual replacement.' -ForegroundColor Yellow
}
Write-Host "RESTORE COPY COMPLETE: $RestoreRoot" -ForegroundColor Green
Write-Host 'Dependencies and compiled binaries are excluded; rebuild/reinstall before launching this restored copy.'
